# Telegram Abridger Userbot

## Requirements

- Python 3.10+
- `telethon`
- Telegram API credentials (`API_ID`, `API_HASH`)

### Getting API_ID and API_HASH

1. Go to https://my.telegram.org and sign in with your phone number
2. Navigate to **API development tools**
3. Create an application (name and platform can be anything)
4. Copy `App api_id` → `API_ID` and `App api_hash` → `API_HASH`

### Config (env vars or `.env`)

| Variable | Default | Description |
|---|---|---|
| `API_ID` | — | Telegram API ID |
| `API_HASH` | — | Telegram API Hash |
| `COOLDOWN_INTERVAL` | `300` | Observation window in seconds |
| `MESSAGE_FREQUENCY_LIMIT` | `5` | Max messages per window before muting |
| `MESSAGE_CONCAT_STRING` | `, ` | Delimiter used to join buffered messages |
| `MUTE_TIMEOUT` | `3600` | Mute duration in seconds |
| `SUMMARY_PREFIX` | _(none)_ | Optional prefix prepended to the reply; `%d` is replaced with the message count (e.g. `"I've put together your %d messages:\n"`) |

## Usage

```bash
cp .env.example .env  # fill in API_ID and API_HASH
uv run bot.py
```

`uv` installs dependencies from the script's inline metadata (PEP 723) into an isolated environment.

On first run, Telethon will prompt for your phone number and confirmation code.

## How it works

The userbot monitors incoming messages from non-muted, non-archived chats (forum/topics chats are excluded). For each sender it maintains a sliding window of `COOLDOWN_INTERVAL` seconds:

- Incoming messages are marked as read and added to a per-sender buffer
- If a sender exceeds `MESSAGE_FREQUENCY_LIMIT` messages within the window, they are muted for `MUTE_TIMEOUT` seconds via Telegram's notification settings
- Buffered messages are concatenated with `MESSAGE_CONCAT_STRING` and sent silently in the same chat; if `SUMMARY_PREFIX` is set, it is prepended to the reply (`%d` → message count)
- Buffers are also flushed periodically once a sender's window expires
- If the user sent any messages in the same chat within `COOLDOWN_INTERVAL`, the summary is suppressed — the conversation is already active

## Output / Result Files

- `userbot.session` — Telethon session file (do not commit)
- Logs go to stdout
