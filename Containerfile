# syntax=docker/dockerfile:1

# Build stage: resolve and install dependencies into a virtual environment.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install dependencies from the lockfile in a cached, reproducible layer.
# The project itself is not a package (tool.uv.package = false), so only
# third-party dependencies land in the virtual environment.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev

COPY bot.py /app/bot.py

# Runtime stage: a slim image without uv. The interpreter path must match the
# builder image, hence the same python:3.13 base.
FROM python:3.13-slim-bookworm

RUN groupadd --system --gid 999 nonroot \
    && useradd --system --gid 999 --uid 999 --create-home nonroot

COPY --from=builder --chown=nonroot:nonroot /app /app

# Put the virtual environment's executables first on PATH.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    SESSION=/data/userbot

# Telethon persists its session at $SESSION.session; mount a volume on /data to
# keep authentication across restarts.
RUN install --directory --owner=nonroot --group=nonroot /data
VOLUME ["/data"]

USER nonroot
WORKDIR /app

ENTRYPOINT ["python", "bot.py"]
