# Telegram Abridger Userbot

[English](README.md) · **中文** · [Русский](README.ru.md)

一个以用户账号身份运行的 MTProto userbot：它监听收到的消息，按发送者在滑动时间窗内缓存消息；当某个发送者在窗口内刷屏时，将缓存的消息合并为一条静默的摘要发出，并静音该发送者的通知。如果你自己在该聊天里回复过，则不会发送摘要——对话显然正在进行中。

## 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Telegram API 凭据（`API_ID`、`API_HASH`）

### 获取 API_ID 和 API_HASH

1. 打开 https://my.telegram.org 并用手机号登录
2. 进入 **API development tools**
3. 创建一个应用（名称和平台任意）
4. 复制 `App api_id` → `API_ID`，`App api_hash` → `API_HASH`

### 配置（环境变量或 `.env`）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `API_ID` | — | Telegram API ID（必填） |
| `API_HASH` | — | Telegram API hash（必填） |
| `COOLDOWN_INTERVAL` | `300` | 观察窗口，单位秒 |
| `MESSAGE_FREQUENCY_LIMIT` | `5` | 触发静音前每个窗口允许的最大消息数 |
| `MESSAGE_CONCAT_STRING` | `, ` | 拼接缓存消息时使用的分隔符 |
| `MUTE_TIMEOUT` | `3600` | 静音时长，单位秒 |
| `SUMMARY_PREFIX` | _（无）_ | 可选的摘要前缀；`%d` 会被替换为消息数量（例如 `"I've put together your %d messages:\n"`） |
| `SESSION` | `userbot` | Telethon 会话名称或路径；认证信息保存在 `$SESSION.session` |

## 使用方法

```bash
cp .env.example .env  # 填入 API_ID 和 API_HASH
uv run bot.py
```

`uv run` 会自动根据 `pyproject.toml`/`uv.lock` 解析并安装依赖到隔离环境中，无需手动配置。

首次运行时，Telethon 会要求输入手机号和验证码，然后写入一个 `*.session` 文件。该文件包含你的认证密钥——请妥善保管，切勿提交到版本库。

## 在容器中运行

镜像在 `uv` 构建阶段安装依赖，并以精简的非 root 运行时发布。会话保存在 `/data` 卷上，因此重启后认证依然有效。

```bash
# 构建
docker build --tag telegram-abridger --file Containerfile .

# 首次运行：交互式登录，并将会话持久化到命名卷
docker run --interactive --tty \
  --env-file .env \
  --volume abridger-session:/data \
  telegram-abridger

# 之后运行（已完成登录）
docker run --detach --restart unless-stopped \
  --env-file .env \
  --volume abridger-session:/data \
  telegram-abridger
```

镜像已设置 `SESSION=/data/userbot`；请在 `.env` 中不要设置 `SESSION`，以便会话保存到卷上。

## 工作原理

userbot 监听来自未静音、未归档聊天的收到消息（排除论坛/话题类聊天）。它为每个发送者维护一个 `COOLDOWN_INTERVAL` 秒的滑动窗口：

- 收到的消息会被标记为已读，并加入按发送者区分的缓冲区
- 如果某个发送者在窗口内超过 `MESSAGE_FREQUENCY_LIMIT` 条消息，则通过 Telegram 的通知设置将其静音 `MUTE_TIMEOUT` 秒，并立即清空其缓冲区
- 缓存的消息用 `MESSAGE_CONCAT_STRING` 拼接后，在同一聊天里静默发送；若设置了 `SUMMARY_PREFIX`，则将其加在摘要前面（`%d` → 消息数量）
- 当某个发送者的窗口安静下来后，缓冲区也会被定期清空
- 如果你在 `COOLDOWN_INTERVAL` 内于同一聊天发送过任何消息，摘要将被抑制——对话正在进行中

## 开发

```bash
uv sync          # 安装运行时与开发依赖
uv run pytest    # 运行测试
uv run ruff check . && uv run ruff format --check .
uv run mypy bot.py
```

## 输出 / 结果文件

- `$SESSION.session`（默认 `userbot.session`）—— Telethon 会话文件（不要提交）
- 日志输出到 stdout
