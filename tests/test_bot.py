"""Unit tests for the abridger userbot.

Pure logic is tested directly; Telegram-facing paths use an AsyncMock client.
Timing is driven by an injected FakeClock so no test depends on wall-clock time.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import Abridger, Config, ConfigError, _format_prefix


class FakeClock:
    """A deterministic, manually advanced monotonic clock."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def make_config(**overrides):
    base = {
        "api_id": 1,
        "api_hash": "hash",
        "cooldown_interval": 100.0,
        "message_frequency_limit": 2,
        "message_concat_string": ", ",
    }
    base.update(overrides)
    return Config(**base)


def make_bot(clock=None, client=None, **config_overrides):
    clock = clock or FakeClock()
    client = client or AsyncMock()
    return Abridger(client, make_config(**config_overrides), clock=clock), clock, client


def make_event(chat_id, sender_id, text):
    return SimpleNamespace(chat_id=chat_id, sender_id=sender_id, raw_text=text, message=object())


def make_dialog(dialog_id, *, archived=False, forum=False, mute_until=None):
    entity = SimpleNamespace(forum=forum)
    dialog = SimpleNamespace(notify_settings=SimpleNamespace(mute_until=mute_until))
    return SimpleNamespace(id=dialog_id, archived=archived, entity=entity, dialog=dialog)


# -- Config -----------------------------------------------------------------


def test_config_defaults():
    config = Config.from_env({"API_ID": "42", "API_HASH": "abc"})
    assert config.api_id == 42
    assert config.api_hash == "abc"
    assert config.session == "userbot"
    assert config.cooldown_interval == 300.0
    assert config.message_frequency_limit == 5
    assert config.message_concat_string == ", "
    assert config.mute_timeout == 3600.0
    assert config.summary_prefix == ""


def test_config_full_override():
    config = Config.from_env(
        {
            "API_ID": "7",
            "API_HASH": "h",
            "SESSION": "/data/userbot",
            "COOLDOWN_INTERVAL": "60",
            "MESSAGE_FREQUENCY_LIMIT": "3",
            "MESSAGE_CONCAT_STRING": " | ",
            "MUTE_TIMEOUT": "120",
            "SUMMARY_PREFIX": "got %d:",
        }
    )
    assert config.session == "/data/userbot"
    assert config.cooldown_interval == 60.0
    assert config.message_frequency_limit == 3
    assert config.message_concat_string == " | "
    assert config.mute_timeout == 120.0
    assert config.summary_prefix == "got %d:"


def test_config_missing_api_id():
    with pytest.raises(ConfigError, match="API_ID is required"):
        Config.from_env({"API_HASH": "h"})


def test_config_missing_api_hash():
    with pytest.raises(ConfigError, match="API_HASH is required"):
        Config.from_env({"API_ID": "1"})


def test_config_non_int_api_id():
    with pytest.raises(ConfigError, match="API_ID must be an integer"):
        Config.from_env({"API_ID": "not-a-number", "API_HASH": "h"})


# -- _format_prefix ---------------------------------------------------------


def test_format_prefix_with_placeholder():
    assert _format_prefix("got %d msgs", 3) == "got 3 msgs"


def test_format_prefix_without_placeholder():
    assert _format_prefix("Summary: ", 3) == "Summary: "


def test_format_prefix_escaped_percent():
    assert _format_prefix("50%% done, %d items: ", 3) == "50% done, 3 items: "


# -- is_muted ---------------------------------------------------------------


def test_is_muted_not_muted():
    bot, _clock, _client = make_bot()
    assert bot.is_muted(5) is False


def test_is_muted_active_then_expires():
    bot, clock, _client = make_bot(mute_timeout=50.0)
    bot._mark_muted(5)
    assert bot.is_muted(5) is True
    clock.advance(49)
    assert bot.is_muted(5) is True
    clock.advance(2)
    assert bot.is_muted(5) is False
    assert 5 not in bot._muted_until


# -- register_message -------------------------------------------------------


def test_register_message_under_limit():
    bot, _clock, _client = make_bot(message_frequency_limit=2)
    assert bot.register_message(1, 9, "a") is False
    assert bot.register_message(1, 9, "b") is False


def test_register_message_over_limit():
    bot, _clock, _client = make_bot(message_frequency_limit=2)
    bot.register_message(1, 9, "a")
    bot.register_message(1, 9, "b")
    assert bot.register_message(1, 9, "c") is True


def test_register_message_trims_old_timestamps():
    bot, clock, _client = make_bot(message_frequency_limit=2, cooldown_interval=100.0)
    bot.register_message(1, 9, "a")
    clock.advance(101)
    assert bot.register_message(1, 9, "b") is False
    assert bot.register_message(1, 9, "c") is False
    assert bot.register_message(1, 9, "d") is True


def test_register_message_buffers_text():
    bot, _clock, _client = make_bot()
    bot.register_message(1, 9, "hello")
    bot.register_message(1, 9, "world")
    assert bot._buffer[(1, 9)] == ["hello", "world"]


# -- outgoing / active conversation -----------------------------------------


def test_replied_recently_true_then_expires():
    bot, clock, _client = make_bot(cooldown_interval=100.0)
    assert bot.replied_recently(1) is False
    bot.record_outgoing(1)
    assert bot.replied_recently(1) is True
    clock.advance(101)
    assert bot.replied_recently(1) is False


# -- take_sender_buffers / drainable_senders --------------------------------


def test_take_sender_buffers_only_target_sender():
    bot, _clock, _client = make_bot()
    bot._buffer[(1, 9)] = ["a"]
    bot._buffer[(2, 9)] = ["b", "c"]
    bot._buffer[(1, 8)] = ["x"]
    assert dict(bot.take_sender_buffers(9)) == {1: ["a"], 2: ["b", "c"]}
    assert (1, 9) not in bot._buffer
    assert (2, 9) not in bot._buffer
    assert (1, 8) in bot._buffer


def test_drainable_senders_quiet_is_ready():
    bot, clock, _client = make_bot(cooldown_interval=100.0, message_frequency_limit=5)
    bot.register_message(1, 9, "a")
    clock.advance(101)
    assert bot.drainable_senders() == [(1, 9)]


def test_drainable_senders_active_not_ready():
    bot, _clock, _client = make_bot(cooldown_interval=100.0)
    bot.register_message(1, 9, "a")
    assert bot.drainable_senders() == []


def test_drainable_senders_drops_muted():
    bot, _clock, _client = make_bot(cooldown_interval=100.0, mute_timeout=500.0)
    bot.register_message(1, 9, "a")
    bot._mark_muted(9)
    assert bot.drainable_senders() == []
    assert (1, 9) not in bot._buffer


# -- _send_buffer -----------------------------------------------------------


async def test_send_buffer_joins_silently():
    bot, _clock, client = make_bot(message_concat_string=" | ")
    await bot._send_buffer(7, ["a", "b", "c"])
    client.send_message.assert_awaited_once_with(7, "a | b | c", silent=True)


async def test_send_buffer_applies_prefix_with_count():
    bot, _clock, client = make_bot(summary_prefix="got %d: ")
    await bot._send_buffer(7, ["a", "b"])
    client.send_message.assert_awaited_once_with(7, "got 2: a, b", silent=True)


async def test_send_buffer_skips_empty():
    bot, _clock, client = make_bot()
    await bot._send_buffer(7, [])
    client.send_message.assert_not_awaited()


async def test_send_buffer_skips_active_conversation():
    bot, _clock, client = make_bot()
    bot.record_outgoing(7)
    await bot._send_buffer(7, ["a"])
    client.send_message.assert_not_awaited()


# -- _mute_peer -------------------------------------------------------------


async def test_mute_peer_success_marks_muted():
    bot, _clock, client = make_bot(mute_timeout=100.0)
    await bot._mute_peer(9)
    client.get_input_entity.assert_awaited_once_with(9)
    assert client.call_count == 1
    assert bot.is_muted(9) is True


async def test_mute_peer_failure_does_not_mark():
    bot, _clock, client = make_bot()
    client.get_input_entity.side_effect = RuntimeError("boom")
    await bot._mute_peer(9)
    assert bot.is_muted(9) is False


# -- on_message / on_outgoing -----------------------------------------------


async def test_on_message_ignores_inactive_chat():
    bot, _clock, client = make_bot()
    await bot.on_message(make_event(1, 9, "hi"))
    client.send_read_acknowledge.assert_not_awaited()


async def test_on_message_ignores_muted_sender():
    bot, _clock, client = make_bot()
    bot._active_chats.add(1)
    bot._mark_muted(9)
    await bot.on_message(make_event(1, 9, "hi"))
    client.send_read_acknowledge.assert_not_awaited()


async def test_on_message_ignores_empty_text():
    bot, _clock, client = make_bot()
    bot._active_chats.add(1)
    await bot.on_message(make_event(1, 9, ""))
    client.send_read_acknowledge.assert_not_awaited()


async def test_on_message_accumulates_and_acks():
    bot, _clock, client = make_bot(message_frequency_limit=5)
    bot._active_chats.add(1)
    await bot.on_message(make_event(1, 9, "hi"))
    client.send_read_acknowledge.assert_awaited_once()
    assert bot._buffer[(1, 9)] == ["hi"]
    client.send_message.assert_not_awaited()


async def test_on_message_flood_flushes_and_mutes():
    bot, _clock, client = make_bot(message_frequency_limit=2)
    bot._active_chats.add(1)
    for text in ("a", "b", "c"):
        await bot.on_message(make_event(1, 9, text))
    client.send_message.assert_awaited_once_with(1, "a, b, c", silent=True)
    assert bot.is_muted(9) is True
    assert (1, 9) not in bot._buffer


async def test_on_outgoing_records():
    bot, _clock, _client = make_bot()
    await bot.on_outgoing(SimpleNamespace(chat_id=5))
    assert bot.replied_recently(5) is True


async def test_on_outgoing_ignores_no_chat():
    bot, _clock, _client = make_bot()
    await bot.on_outgoing(SimpleNamespace(chat_id=0))
    assert bot.replied_recently(0) is False


# -- refresh_active_chats / flush_all ---------------------------------------


async def test_refresh_active_chats_filters():
    future = datetime.now(UTC) + timedelta(hours=1)
    dialogs = [
        make_dialog(1),
        make_dialog(2, archived=True),
        make_dialog(3, forum=True),
        make_dialog(4, mute_until=future),
    ]

    async def gen():
        for dialog in dialogs:
            yield dialog

    client = AsyncMock()
    client.iter_dialogs = gen
    bot = Abridger(client, make_config(), clock=FakeClock())
    await bot.refresh_active_chats()
    assert bot._active_chats == {1}


async def test_flush_all_sends_everything():
    bot, _clock, client = make_bot()
    bot._buffer[(1, 9)] = ["a"]
    bot._buffer[(2, 8)] = ["b", "c"]
    await bot.flush_all()
    assert client.send_message.await_count == 2
    assert dict(bot._buffer) == {}
