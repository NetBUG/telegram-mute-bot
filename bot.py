"""Telegram abridger userbot.

A self-account (MTProto) userbot that watches incoming messages, buffers them
per sender over a sliding window, and—when a sender floods the window—joins the
buffered messages into one silent summary and mutes the sender's notifications.
If the account owner has replied in the chat during the window, the summary is
skipped: the conversation is clearly active.

Networking is provided by Telethon. All rate-limiting and buffering logic lives
in :class:`Abridger` and is decoupled from the clock and the client so it can be
unit-tested without touching Telegram.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl import functions, types

log = logging.getLogger("abridger")

#: A monotonic clock returning seconds. Injected to make timing testable.
Clock = Callable[[], float]


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed."""


@dataclass(frozen=True, slots=True)
class Config:
    """Runtime configuration, normally built from the environment."""

    api_id: int
    api_hash: str
    session: str = "userbot"
    cooldown_interval: float = 300.0
    message_frequency_limit: int = 5
    message_concat_string: str = ", "
    mute_timeout: float = 3600.0
    summary_prefix: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        """Build a :class:`Config` from a mapping (``os.environ`` by default)."""
        source: Mapping[str, str] = os.environ if env is None else env
        try:
            raw_api_id = source["API_ID"]
        except KeyError:
            raise ConfigError("API_ID is required") from None
        try:
            api_id = int(raw_api_id)
        except ValueError as exc:
            raise ConfigError("API_ID must be an integer") from exc
        try:
            api_hash = source["API_HASH"]
        except KeyError:
            raise ConfigError("API_HASH is required") from None
        return cls(
            api_id=api_id,
            api_hash=api_hash,
            session=source.get("SESSION", "userbot"),
            cooldown_interval=float(source.get("COOLDOWN_INTERVAL", "300")),
            message_frequency_limit=int(source.get("MESSAGE_FREQUENCY_LIMIT", "5")),
            message_concat_string=source.get("MESSAGE_CONCAT_STRING", ", "),
            mute_timeout=float(source.get("MUTE_TIMEOUT", "3600")),
            summary_prefix=source.get("SUMMARY_PREFIX", ""),
        )


def _format_prefix(prefix: str, count: int) -> str:
    """Apply ``count`` to ``prefix`` via ``%`` formatting, tolerating no placeholder."""
    try:
        return prefix % count
    except (TypeError, ValueError):
        return prefix


class Abridger:
    """Buffers messages per sender and mutes senders that flood the window.

    Timing uses an injectable monotonic clock so the sliding window and the
    local mute bookkeeping are immune to wall-clock jumps and easy to test. The
    Telegram-facing mute deadline is the only value derived from wall-clock time,
    and only at the moment the notification setting is changed.
    """

    def __init__(
        self,
        client: TelegramClient,
        config: Config,
        *,
        clock: Clock = time.monotonic,
    ) -> None:
        self._client = client
        self._config = config
        self._clock = clock
        # sender_id -> arrival timestamps within the observation window
        self._timestamps: defaultdict[int, deque[float]] = defaultdict(deque)
        # chat_id -> timestamps of the account owner's own outgoing messages
        self._outgoing: defaultdict[int, deque[float]] = defaultdict(deque)
        # (chat_id, sender_id) -> buffered message texts
        self._buffer: defaultdict[tuple[int, int], list[str]] = defaultdict(list)
        # sender_id -> monotonic expiry of a bot-imposed mute
        self._muted_until: dict[int, float] = {}
        # chat IDs eligible for processing (non-archived, non-forum, non-muted)
        self._active_chats: set[int] = set()
        self._flush_task: asyncio.Task[None] | None = None

    # -- Pure rate-limiting / buffering logic (no network, fully testable) --

    def is_muted(self, sender_id: int) -> bool:
        """Return whether ``sender_id`` is currently muted by the bot."""
        expiry = self._muted_until.get(sender_id)
        if expiry is not None and self._clock() < expiry:
            return True
        self._muted_until.pop(sender_id, None)
        return False

    def _trim_window(self, window: deque[float]) -> None:
        """Drop timestamps older than the observation window."""
        cutoff = self._clock() - self._config.cooldown_interval
        while window and window[0] < cutoff:
            window.popleft()

    def register_message(self, chat_id: int, sender_id: int, text: str) -> bool:
        """Record a message and report whether the sender now exceeds the limit."""
        window = self._timestamps[sender_id]
        window.append(self._clock())
        self._trim_window(window)
        self._buffer[(chat_id, sender_id)].append(text)
        return len(window) > self._config.message_frequency_limit

    def record_outgoing(self, chat_id: int) -> None:
        """Record an outgoing message from the account owner in ``chat_id``."""
        self._outgoing[chat_id].append(self._clock())

    def replied_recently(self, chat_id: int) -> bool:
        """Return whether the account owner replied in ``chat_id`` within the window."""
        window = self._outgoing[chat_id]
        self._trim_window(window)
        return bool(window)

    def _mark_muted(self, sender_id: int) -> None:
        """Record a local mute deadline on the monotonic clock."""
        self._muted_until[sender_id] = self._clock() + self._config.mute_timeout

    def take_sender_buffers(self, sender_id: int) -> list[tuple[int, list[str]]]:
        """Remove and return every ``(chat_id, texts)`` buffer for a sender."""
        keys = [key for key in self._buffer if key[1] == sender_id]
        return [(chat_id, self._buffer.pop((chat_id, sid))) for chat_id, sid in keys]

    def drainable_senders(self) -> list[tuple[int, int]]:
        """Return ``(chat_id, sender_id)`` buffers whose window has gone quiet.

        Muted senders' buffers are dropped: their flood was already flushed and
        re-sending on mute expiry would duplicate it.
        """
        ready: list[tuple[int, int]] = []
        for chat_id, sender_id in list(self._buffer):
            if self.is_muted(sender_id):
                self._buffer.pop((chat_id, sender_id), None)
                continue
            window = self._timestamps[sender_id]
            self._trim_window(window)
            if not window:
                ready.append((chat_id, sender_id))
        return ready

    # -- Telegram-facing operations --

    async def _send_buffer(self, chat_id: int, texts: Sequence[str]) -> None:
        if not texts:
            return
        if self.replied_recently(chat_id):
            log.info("skipped summary for chat=%d (active conversation)", chat_id)
            return
        body = self._config.message_concat_string.join(texts)
        if self._config.summary_prefix:
            body = _format_prefix(self._config.summary_prefix, len(texts)) + body
        await self._client.send_message(chat_id, body, silent=True)
        log.info("sent %d msgs to chat=%d", len(texts), chat_id)

    async def _mute_peer(self, sender_id: int) -> None:
        until = datetime.now(UTC) + timedelta(seconds=self._config.mute_timeout)
        until_ts = int(until.timestamp())
        try:
            entity = await self._client.get_input_entity(sender_id)
            await self._client(
                functions.account.UpdateNotifySettingsRequest(
                    peer=types.InputNotifyPeer(peer=entity),
                    settings=types.InputPeerNotifySettings(mute_until=until_ts),
                )
            )
        except Exception:
            log.exception("failed to mute sender=%d", sender_id)
            return
        self._mark_muted(sender_id)
        log.info("muted sender=%d for %.0fs", sender_id, self._config.mute_timeout)

    async def refresh_active_chats(self) -> None:
        """Rebuild the set of chats eligible for processing."""
        now = time.time()
        active: set[int] = set()
        async for dialog in self._client.iter_dialogs():
            if dialog.archived:
                continue
            if getattr(dialog.entity, "forum", False):
                continue
            mute_until = dialog.dialog.notify_settings.mute_until
            if mute_until is not None and mute_until.timestamp() > now:
                continue
            active.add(dialog.id)
        self._active_chats = active
        log.info("active chats: %d", len(active))

    async def on_outgoing(self, event: events.NewMessage.Event) -> None:
        """Track the account owner's own messages to detect active conversations."""
        if event.chat_id:
            self.record_outgoing(event.chat_id)

    async def on_message(self, event: events.NewMessage.Event) -> None:
        """Handle one incoming message."""
        sender_id = event.sender_id
        chat_id = event.chat_id
        if chat_id not in self._active_chats:
            return
        if not sender_id or self.is_muted(sender_id):
            return
        text = event.raw_text
        if not text:
            return

        over_limit = self.register_message(chat_id, sender_id, text)
        await self._client.send_read_acknowledge(chat_id, event.message)

        if over_limit:
            for chat, texts in self.take_sender_buffers(sender_id):
                await self._send_buffer(chat, texts)
            await self._mute_peer(sender_id)

    async def _flush_quiet_senders(self) -> None:
        for chat_id, sender_id in self.drainable_senders():
            await self._send_buffer(chat_id, self._buffer.pop((chat_id, sender_id), []))

    async def flush_all(self) -> None:
        """Flush every buffered message; used on graceful shutdown."""
        for chat_id, sender_id in list(self._buffer):
            await self._send_buffer(chat_id, self._buffer.pop((chat_id, sender_id), []))

    async def _periodic_flush(self) -> None:
        """Periodically refresh active chats and flush quiet senders' buffers."""
        interval = self._config.cooldown_interval / 2
        while True:
            await asyncio.sleep(interval)
            try:
                await self.refresh_active_chats()
                await self._flush_quiet_senders()
            except Exception:
                log.exception("periodic flush iteration failed")

    async def run(self) -> None:
        """Connect, register handlers, and run until disconnected."""
        await self._client.start()
        me = await self._client.get_me()
        log.info("started as %s (id=%s)", me.username or me.first_name, me.id)
        self._client.add_event_handler(self.on_message, events.NewMessage(incoming=True))
        self._client.add_event_handler(self.on_outgoing, events.NewMessage(outgoing=True))
        await self.refresh_active_chats()
        self._flush_task = asyncio.create_task(self._periodic_flush())
        try:
            await self._client.run_until_disconnected()
        finally:
            if self._flush_task is not None:
                self._flush_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._flush_task
            await self.flush_all()


def install_signal_handlers(client: TelegramClient) -> None:
    """Disconnect the client on SIGINT/SIGTERM so shutdown is graceful."""
    loop = asyncio.get_running_loop()
    pending: set[asyncio.Task[None]] = set()

    def request_stop() -> None:
        log.info("shutdown signal received, disconnecting")
        result = client.disconnect()
        if asyncio.iscoroutine(result):
            # Keep a strong reference until done so the task is not GC'd.
            task = loop.create_task(result)
            pending.add(task)
            task.add_done_callback(pending.discard)

    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, request_stop)


async def main() -> None:
    load_dotenv()
    config = Config.from_env()
    client = TelegramClient(config.session, config.api_id, config.api_hash)
    install_signal_handlers(client)
    await Abridger(client, config).run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
