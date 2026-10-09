# syntax=docker/dockerfile:1

FROM python:3.12.15-slim-trixie AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --no-editable

COPY README.md ./
COPY src/ ./src/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python:3.12.15-slim-trixie AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app \
        --home-dir /app --no-create-home --shell /usr/sbin/nologin app \
    && install -d -m 0755 -o app -g app /app /data

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv

USER app

EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=5s --start-period=10s --retries=12 \
    CMD ["python", "-c", "import json, urllib.request; response = urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3); raise SystemExit(0 if json.load(response).get('status') == 'UP' else 1)"]

CMD ["uvicorn", "ai_incident_investigator.main:app", "--host", "0.0.0.0", "--port", "8000"]