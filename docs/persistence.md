# Investigation persistence

The optional PostgreSQL store saves completed investigation snapshots, including reports
whose analysis failed, was skipped, or remained inconclusive. It does not create
background jobs or run additional model requests.

## Run the Compose demo with persistence

```bash
docker compose -f compose.yaml -f compose.persistence.yaml up --build --wait --wait-timeout 180
uv run --locked python scripts/check_investigation_storage.py
```

The overlay starts PostgreSQL, runs Alembic migrations in a one-shot service, and then
starts the investigator. Its credentials are fixed local demo credentials. PostgreSQL is
published on `127.0.0.1:5433`; containers connect to `postgres:5432`.

The frontend proxy refreshes backend addresses through Docker DNS instead of
keeping the investigator's startup IP. DNS answers are cached for five seconds;
Nginx does not need a restart after the backend is recreated.

Normal restarts preserve the named `investigation-data` volume. Running `docker compose
-f compose.yaml -f compose.persistence.yaml down --volumes` deletes the saved
investigations along with the other Compose volumes.

## Run the backend locally

```bash
docker compose -f compose.yaml -f compose.persistence.yaml up -d --wait postgres
export DATABASE_URL='postgresql+psycopg://investigator:local-demo-only@127.0.0.1:5433/investigator'
uv run --locked alembic upgrade head
LLM_ENABLED=false uv run --locked uvicorn ai_incident_investigator.main:app --reload
```

`get_settings()` reads process environment variables. If you prefer a `.env` file, pass
`uv run --env-file .env` to both the Alembic and Uvicorn commands. The application does
not create tables at startup. A configured but unavailable or unmigrated database
prevents startup. Without `DATABASE_URL`, the original nonpersistent demo remains
available.

## API contract

`POST /investigations` keeps its existing `InvestigationReport` JSON response. When
persistence is enabled, it returns `X-Investigation-ID` only after the snapshot
transaction commits. Use that UUID with `GET /investigations/{investigation_id}` to
retrieve the snapshot. An unknown UUID returns 404 and an invalid UUID returns 422.
Saved-investigation reads return 503 when storage is disabled or unavailable. When
storage is disabled, POST continues to return the ordinary report without an
investigation ID.

Snapshots contain the original request and report, UTC creation time, schema version,
collection-and-analysis duration in milliseconds, configured model, and SHA-256 of the
configured system prompt. Duration excludes persistence and dependency initialization.
Model and prompt fields describe configuration, not proof of an API request or the
provider's actual returned model. Token usage and cost accounting are separate features.

The HTTP route calls the application workflow `execute_investigation()`. The workflow
first calls the core `investigate()` pipeline, then saves the completed snapshot through
the `InvestigationStore` port. `storage/repository.py` provides the SQLAlchemy
implementation; the workflow does not depend on FastAPI, SQLAlchemy, or the OpenAI SDK.

No database transaction is held during source collection or LLM analysis. Saving uses a
short transaction after the report is computed. If saving fails, POST returns 503.
Retrying can repeat collection and a billable LLM request; idempotent requests and
background retries are not implemented yet.

The API exposes no update/delete operations for snapshots. History lists, filters, and
React detail pages will be added separately. The current UI keeps one report in memory;
it does not reload a saved snapshot after a refresh.

The evaluation runner bypasses the persistence workflow and calls `investigate()`
directly. Its run artifacts remain files and are not inserted into this snapshot store.

## Test databases

```bash
uv run --locked pytest
TEST_DATABASE_URL='postgresql+psycopg://investigator:test-only@127.0.0.1:5434/investigator_test' \
  uv run --locked pytest -m postgres
```

The PostgreSQL test database must already exist and its name must end in `_test`. The
database fixtures and adapter/API tests live under `tests/storage/`; fixtures do not
apply to unrelated Python tests. Every PostgreSQL test creates, migrates, and removes
only its own random schema. SQLite tests run without Docker; PostgreSQL tests
additionally verify real JSONB and migration compatibility.

## Code boundaries

- `investigations/records.py` defines the `StoredInvestigation` contract.
- `investigations/ports.py` defines `InvestigationStore` and `StorageError`.
- `investigations/workflow.py` owns pipeline execution followed by optional save.
- `storage/` contains SQLAlchemy tables, engine setup, and the repository adapter.
- `dependencies.py` wires configured providers into HTTP dependencies; model
  and prompt configuration enter the workflow as application data.
- `main.py` exposes `create_app()` and the existing `app` ASGI entry point.

The workflow returns a report and an optional saved investigation ID. The HTTP route
maps those values to the existing response JSON and ID header; it maps storage errors to
HTTP status codes. Non-HTTP callers can reuse the workflow without importing FastAPI, or
call `investigate()` directly when no persistence is required.
