# AI Incident Investigator

An AI assistant for investigating service incidents.

## Current status

Project bootstrap: FastAPI application, health endpoint,
automated tests, and code quality checks.

AI investigation is not implemented yet.

## Requirements

- uv
- Python 3.12, managed by uv

## Setup

```bash
uv python install
uv sync --locked --dev
```

## Run locally

```bash
uv run uvicorn ai_incident_investigator.main:app --reload
```

- Health: http://127.0.0.1:8000/health
- API documentation: http://127.0.0.1:8000/docs

## Run checks

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

## Next milestone

Implement POST /v1/investigations with validated input,
structured incident reports, and an LLM provider adapter.