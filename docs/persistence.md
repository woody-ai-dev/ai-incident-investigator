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

The API exposes no update/delete operations for snapshots. The React history page
loads summaries separately from the full report and preserves filters and pagination
in its URL. Direct snapshot URLs work after a browser refresh through Vite or Nginx.

The evaluation runner bypasses the persistence workflow and calls `investigate()`
directly. Its run artifacts remain files and are not inserted into this snapshot store.

## Browse history in the UI

After starting the persistence overlay, open `http://127.0.0.1:3000/investigations`.
Create a new investigation if the list is empty. The sidebar switches between **New
investigation** and **Investigations**. The existing in-memory workspace is left when
you navigate away; saved snapshots remain in PostgreSQL.

- Choose service and environment filters from the same floating selectors as the main
  investigation form. **All services** / **All environments** remove that filter.
  Options combine configured demo targets, values in the current result page, and
  selected URL filters, so historical links remain usable. This is not service discovery.
- **Created from** is inclusive and **Created until** is exclusive. These filter when
  an investigation was saved, not the time window of the incident. UI dates use the
  browser timezone and are sent as UTC. History ranges have no one-hour limit.
- **Older investigations** loads the next page. **Newest results** returns to the
  beginning. Changing filters resets pagination; Back/Forward and direct links restore
  the URL's filters. **Back to investigations** keeps the list query.
- **Open report** loads the immutable snapshot. Its evidence flow shows saved counts,
  not current source health. **Copy report link** copies a clean snapshot URL without
  list filters. JSON export retains the existing request/report envelope.
- Loading, empty, missing, invalid, and unavailable states have explicit messages.
  Retry repeats only a read. A missing storage connection does not disable new
  investigations. A stopped POST may still finish on the server and appear in history.

A configured model is configuration metadata; it is not proof that a model was called.
“Analysis completed” means a response passed structural validation, not that its
reasoning is correct. The UI does not store credentials or reports in localStorage.
Links require access to the same running application; authentication and authorization
are not implemented in this local demo.

## History list API

```bash
curl --get http://127.0.0.1:8000/investigations \
  --data-urlencode 'service=order-service' \
  --data-urlencode 'environment=local' \
  --data-urlencode 'created_from=2026-10-20T00:00:00Z' \
  --data-urlencode 'created_until=2026-10-21T00:00:00Z' \
  --data-urlencode 'limit=20'
```

`GET /investigations` accepts optional `service`, `environment`, `created_from`,
`created_until`, `cursor`, and `limit` (default 20; 1–100). Dates must include a timezone;
invalid ranges, malformed cursors, and unknown query parameters return 422.
The result is `{ "items": [...], "next_cursor": null | "..." }`. Each item contains
`id`, `created_at`, `service`, `environment`, `duration_ms`, `configured_model`,
`analysis_status`, and `summary`. Full evidence and report JSON are not selected for
list responses. For another page, pass `next_cursor` unchanged as `cursor` with the
same filters. A null cursor means there are no more rows in that query.

Ordering is `created_at DESC, id DESC`; cursor comparisons preserve microseconds and
use UUIDs to break ties. The adapter fetches at most `limit + 1` rows rather than an
unbounded list or an expensive total count. Newer inserts do not shift older pages.
The `0002_history_index` migration adds the matching creation-time/UUID index without
rewriting existing snapshots. Run `alembic upgrade head` when upgrading an existing DB.
Reads return 503 when storage is disabled or unavailable; database details are not
returned to clients. History does not start collection or model analysis.

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

- `investigations/history.py` defines validated filters, cursors, and list read models.
- `investigations/records.py` defines the `StoredInvestigation` contract.
- `investigations/ports.py` defines `InvestigationWriter`, `InvestigationStore`, and `StorageError`.
- `investigations/workflow.py` owns pipeline execution followed by optional save.
- `storage/` contains SQLAlchemy tables, engine setup, and the repository adapter.
- `dependencies.py` wires configured providers into HTTP dependencies; model
  and prompt configuration enter the workflow as application data.
- `main.py` exposes `create_app()` and the existing `app` ASGI entry point.

The workflow returns a report and an optional saved investigation ID. The HTTP route
maps those values to the existing response JSON and ID header; it maps storage errors to
HTTP status codes. Non-HTTP callers can reuse the workflow without importing FastAPI, or
call `investigate()` directly when no persistence is required.
