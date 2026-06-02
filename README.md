# Telegram Abridger Userbot

[English version](README_en.md)

## Requirements

- Python 3.10+
- `telethon`
- Telegram API credentials (`API_ID`, `API_HASH`)

### Получение API_ID и API_HASH

1. Открыть https://my.telegram.org и войти по номеру телефона
2. Перейти в **API development tools**
3. Создать приложение (название и платформа — любые)
4. Скопировать `App api_id` → `API_ID` и `App api_hash` → `API_HASH`

### Config (env vars or `.env`)

| Variable | Default | Description |
|---|---|---|
| `API_ID` | — | Telegram API ID |
| `API_HASH` | — | Telegram API Hash |
| `COOLDOWN_INTERVAL` | `300` | Окно наблюдения в секундах |
| `MESSAGE_FREQUENCY_LIMIT` | `5` | Макс. сообщений за окно до mute |
| `MESSAGE_CONCAT_STRING` | `, ` | Разделитель при склейке сообщений |

## Usage

```bash
cp .env.example .env  # заполни API_ID и API_HASH
uv run bot.py
```

`uv` сам установит зависимости из inline-метаданных скрипта (PEP 723) в изолированное окружение.

При первом запуске Telethon запросит номер телефона и код подтверждения.

## Output / Result Files

- `userbot.session` — файл сессии Telethon (не коммитить)
- Логи выводятся в stdout
