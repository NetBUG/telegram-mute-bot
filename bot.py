# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "telethon>=1.36",
#   "python-dotenv>=1.0",
# ]
# ///

import asyncio
import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl import functions, types

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
COOLDOWN_INTERVAL = int(os.getenv("COOLDOWN_INTERVAL", "300"))       # seconds
MESSAGE_FREQUENCY_LIMIT = int(os.getenv("MESSAGE_FREQUENCY_LIMIT", "5"))
MESSAGE_CONCAT_STRING = os.getenv("MESSAGE_CONCAT_STRING", ", ")
MUTE_DURATION = 3600  # 1 hour

client = TelegramClient("userbot", API_ID, API_HASH)

# sender_id -> deque of arrival timestamps (epoch floats)
timestamps: dict[int, deque] = defaultdict(deque)
# (chat_id, sender_id) -> accumulated texts
buffer: dict[tuple[int, int], list[str]] = defaultdict(list)
# sender_id -> expiry timestamp (bot-imposed rate-limit mutes)
muted_until: dict[int, float] = {}
# chat IDs that are not archived and not user-muted
active_chats: set[int] = set()


def is_muted(sender_id: int) -> bool:
    expiry = muted_until.get(sender_id)
    if expiry and time.time() < expiry:
        return True
    muted_until.pop(sender_id, None)
    return False


def trim_window(dq: deque) -> None:
    cutoff = time.time() - COOLDOWN_INTERVAL
    while dq and dq[0] < cutoff:
        dq.popleft()


async def send_buffer(chat_id: int, sender_id: int) -> None:
    texts = buffer.pop((chat_id, sender_id), [])
    if not texts:
        return
    await client.send_message(chat_id, MESSAGE_CONCAT_STRING.join(texts), silent=True)
    log.info("sent %d msgs from sender=%d in chat=%d", len(texts), sender_id, chat_id)


async def refresh_active_chats() -> None:
    now = time.time()
    new_active: set[int] = set()
    async for dialog in client.iter_dialogs():
        if dialog.archived:
            continue
        if getattr(dialog.entity, "forum", False):
            continue
        mute_until = dialog.dialog.notify_settings.mute_until
        if mute_until and mute_until.timestamp() > now:
            continue
        new_active.add(dialog.id)
    active_chats.clear()
    active_chats.update(new_active)
    log.info("active chats: %d", len(active_chats))


async def mute_peer(sender_id: int) -> None:
    until_ts = int((datetime.now(timezone.utc) + timedelta(seconds=MUTE_DURATION)).timestamp())
    try:
        entity = await client.get_input_entity(sender_id)
        await client(
            functions.account.UpdateNotifySettingsRequest(
                peer=types.InputNotifyPeer(peer=entity),
                settings=types.InputPeerNotifySettings(mute_until=until_ts),
            )
        )
        muted_until[sender_id] = float(until_ts)
        log.info("muted sender=%d for %ds", sender_id, MUTE_DURATION)
    except Exception:
        log.exception("failed to mute sender=%d", sender_id)


@client.on(events.NewMessage(incoming=True))
async def on_message(event: events.NewMessage.Event) -> None:
    sender_id = event.sender_id
    chat_id = event.chat_id
    if chat_id not in active_chats:
        return
    if not sender_id or is_muted(sender_id):
        return

    text = event.raw_text
    if not text:
        return

    dq = timestamps[sender_id]
    dq.append(time.time())
    trim_window(dq)
    buffer[(chat_id, sender_id)].append(text)

    await client.send_read_acknowledge(chat_id, event.message)

    if len(dq) > MESSAGE_FREQUENCY_LIMIT:
        for key in [k for k in list(buffer) if k[1] == sender_id]:
            await send_buffer(*key)
        await mute_peer(sender_id)


async def periodic_flush() -> None:
    """Flush buffered messages for senders whose COOLDOWN_INTERVAL window has expired.
    Also refreshes the active_chats set."""
    while True:
        await asyncio.sleep(COOLDOWN_INTERVAL / 2)
        await refresh_active_chats()
        for (chat_id, sender_id) in list(buffer):
            if is_muted(sender_id):
                buffer.pop((chat_id, sender_id), None)
                continue
            dq = timestamps[sender_id]
            trim_window(dq)
            if not dq:
                await send_buffer(chat_id, sender_id)


async def main() -> None:
    await client.start()
    me = await client.get_me()
    log.info("started as %s (id=%d)", me.username or me.first_name, me.id)
    await refresh_active_chats()
    asyncio.create_task(periodic_flush())
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
