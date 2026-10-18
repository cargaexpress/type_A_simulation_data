# syntax=docker/dockerfile:1
#
# Dockerfile del SIMULADOR DE WEBHOOKS (RIWI-86). Es independiente del backend:
# imagen propia, dependencias propias y ciclo de vida propio.
# Toda la configuración llega por variables de entorno SIM_* (ver README.md).

# ---------- Etapa 1: instalar dependencias ----------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---------- Etapa de pruebas (incluye pytest) ----------
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

CMD ["pytest", "-q"]

# ---------- Etapa final: imagen de ejecución (la que se publica) ----------
FROM python:3.12-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN useradd --system --no-create-home --uid 10001 simulator

COPY --from=builder /app/.venv /app/.venv
COPY webhook_simulator ./webhook_simulator

USER simulator

# Por defecto: envía a http://sink:9000/webhooks/{carrier} (ver docker-compose.yml)
CMD ["python", "-m", "webhook_simulator"]
