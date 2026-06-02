# Telegram Abridger Userbot

**English** · [中文](README.zh-CN.md) · [Русский](README.ru.md)

A self-account (MTProto) userbot that watches incoming messages, buffers them per sender over a sliding window, and—when a sender floods the window—joins the buffered messages into one silent summary and mutes the sender's notifications. If you reply in the chat yourself, the summary is suppressed: the conversation is clearly active.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Telegram API credentials (`API_ID`, `API_HASH`)

### Getting API_ID and API_HASH

1. Go to https://my.telegram.org and sign in with your phone number
2. Navigate to **API development tools**
3. Create an application (name and platform can be anything)
4. Copy `App api_id` → `API_ID` and `App api_hash` → `API_HASH`

### Configuration (environment variables or `.env`)

| Variable | Default | Description |
| --- | --- | --- |
| `API_ID` | — | Telegram API ID (required) |
| `API_HASH` | — | Telegram API hash (required) |
| `COOLDOWN_INTERVAL` | `300` | Observation window in seconds |
| `MESSAGE_FREQUENCY_LIMIT` | `5` | Max messages per window before muting |
| `MESSAGE_CONCAT_STRING` | `, ` | Delimiter used to join buffered messages |
| `MUTE_TIMEOUT` | `3600` | Mute duration in seconds |
| `SUMMARY_PREFIX` | _(none)_ | Optional prefix prepended to the summary; `%d` is replaced with the message count (e.g. `"I've put together your %d messages:\n"`) |
| `SESSION` | `userbot` | Telethon session name or path; auth is stored at `$SESSION.session` |

## Usage

```bash
cp .env.example .env  # fill in API_ID and API_HASH
uv run bot.py
```

`uv run` resolves and installs the dependencies from `pyproject.toml`/`uv.lock` into an isolated environment automatically — no manual setup is needed.

On first run, Telethon will prompt for your phone number and a confirmation code, then write a `*.session` file. That file holds your authentication secret — keep it private and never commit it.

## Running in a container

The image builds dependencies in a `uv` stage and ships a slim, non-root runtime. The session is persisted on the `/data` volume so authentication survives restarts.

```bash
# Build
docker build --tag telegram-abridger --file Containerfile .

# First run: authenticate interactively, persisting the session to a named volume
docker run --interactive --tty \
  --env-file .env \
  --volume abridger-session:/data \
  telegram-abridger

# Subsequent runs (already authenticated)
docker run --detach --restart unless-stopped \
  --env-file .env \
  --volume abridger-session:/data \
  telegram-abridger
```

The image sets `SESSION=/data/userbot`; leave `SESSION` unset in your `.env` so the session lands on the volume.

## How it works

The userbot monitors incoming messages from non-muted, non-archived chats (forum/topics chats are excluded). For each sender it maintains a sliding window of `COOLDOWN_INTERVAL` seconds:

- Incoming messages are marked as read and added to a per-sender buffer
- If a sender exceeds `MESSAGE_FREQUENCY_LIMIT` messages within the window, they are muted for `MUTE_TIMEOUT` seconds via Telegram's notification settings and their buffer is flushed immediately
- Buffered messages are concatenated with `MESSAGE_CONCAT_STRING` and sent silently in the same chat; if `SUMMARY_PREFIX` is set, it is prepended to the summary (`%d` → message count)
- Buffers are also flushed periodically once a sender's window goes quiet
- If you sent any message in the same chat within `COOLDOWN_INTERVAL`, the summary is suppressed — the conversation is already active

## Development

```bash
uv sync          # install runtime + dev dependencies
uv run pytest    # run the test suite
uv run ruff check . && uv run ruff format --check .
uv run mypy bot.py
```

## Output / result files

- `$SESSION.session` (default `userbot.session`) — Telethon session file (do not commit)
- Logs go to stdout
