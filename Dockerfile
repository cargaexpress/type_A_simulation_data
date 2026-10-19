# syntax=docker/dockerfile:1
#
# One image, two services: the SAME image runs the receiver API or the simulator, depending on
# the command docker-compose.yml gives it. Everything is configured with environment variables
# (SIM_* for the simulator, RECEIVER_* for the receiver; see README.md).

# ---------- Stage 1: install production dependencies ----------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Only the dependency files first: this layer stays cached until dependencies change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---------- Test stage (adds pytest + ruff): `docker compose run --rm tests` ----------
FROM python:3.12-slim AS test

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

COPY webhook_simulator ./webhook_simulator
COPY tests ./tests

CMD ["sh", "-c", "ruff check . && pytest -q"]

# ---------- Final stage: the runtime image (this is the one you ship) ----------
FROM python:3.12-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RECEIVER_DB_PATH=/data/events.db \
    SIM_TARGET_URL_TEMPLATE="http://receiver:9000/webhooks/{carrier}"

WORKDIR /app

# Never run as root. /data is where the receiver keeps its SQLite file; creating it here, owned
# by our user, means a fresh docker volume mounted on it is writable from the first start.
RUN useradd --system --no-create-home --uid 10001 app \
    && mkdir /data \
    && chown app:app /data

COPY --from=builder /app/.venv /app/.venv
COPY webhook_simulator ./webhook_simulator

USER app

# Default = the simulator. The receiver service overrides this in docker-compose.yml.
# (SIM_TARGET_URL_TEMPLATE above points at the compose service called "receiver".)
CMD ["python", "-m", "webhook_simulator"]
