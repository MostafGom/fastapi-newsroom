# syntax=docker/dockerfile:1

FROM node:22-alpine AS assets
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json frontend/
RUN npm ci --prefix frontend
COPY frontend frontend
COPY src/newsroom/templates src/newsroom/templates
RUN npm run build --prefix frontend

FROM python:3.14-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY README.md alembic.ini alembic_analytics.ini ./
COPY src ./src
COPY --from=assets /app/src/newsroom/static/dist ./src/newsroom/static/dist
COPY migrations ./migrations
COPY migrations_analytics ./migrations_analytics
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.14-slim AS runtime
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["uvicorn", "newsroom.asgi:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
