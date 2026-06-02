# Telegram Abridger Userbot

[English version](README_en.md)

## Что делает бот

Юзербот входит в Telegram от имени пользователя и следит за входящими сообщениями во всех чатах, которые не заглушены и не находятся в архиве (чаты с topics игнорируются).

Для каждого отправителя ведётся скользящее окно `COOLDOWN_INTERVAL` секунд:

- Все входящие сообщения автоматически отмечаются прочитанными и накапливаются в буфер
- Когда окно истекает, буфер склеивается через `MESSAGE_CONCAT_STRING` и отправляется в тот же чат без уведомления (silently); если задан `SUMMARY_PREFIX`, он добавляется в начало (`%d` → число сообщений)
- Если отправитель превышает `MESSAGE_FREQUENCY_LIMIT` сообщений за окно, он сразу заглушается на `MUTE_TIMEOUT` секунд, а накопленный буфер отправляется досрочно
- Если за `COOLDOWN_INTERVAL` в том же чате были исходящие сообщения (т.е. пользователь сам отвечал), суммари не отправляется — это нормальный ход разговора

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
| `MUTE_TIMEOUT` | `3600` | Длительность mute в секундах |
| `SUMMARY_PREFIX` | _(нет)_ | Префикс перед склеенным сообщением; `%d` заменяется числом сообщений (например, `"Собрано %d сообщений:\n"`) |

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
