# AI Incident Investigator

[![CI (main)](https://github.com/woody-ai-dev/ai-incident-investigator/actions/workflows/ci.yaml/badge.svg?branch=main&event=push)](https://github.com/woody-ai-dev/ai-incident-investigator/actions/workflows/ci.yaml?query=branch%3Amain)
[![Release](https://img.shields.io/github/v/release/woody-ai-dev/ai-incident-investigator)](https://github.com/woody-ai-dev/ai-incident-investigator/releases/latest)

An incident investigation assistant that helps on-call engineers and SREs turn service
telemetry into evidence-backed reports.

The MVP collects evidence from JSONL logs, Prometheus, and Spring Boot Actuator, and
optionally uses OpenAI for structured analysis. A Java demo service generates a
reproducible payment-timeout scenario. Reports combine historical log records and metric
observations with current application identity and health snapshots. Automated
remediation is not implemented.

## Tech stack

| Layer | Technologies |
| --- | --- |
| Backend | Python 3.12+, FastAPI, Pydantic, HTTPX, Uvicorn |
| Persistence | PostgreSQL 17, SQLAlchemy 2, Psycopg 3, Alembic |
| AI analysis | OpenAI Python SDK, Responses API, structured outputs |
| Frontend | React 19, React Router, TypeScript, Vite, Radix UI, Zod |
| Telemetry | JSONL logs, Prometheus, Spring Boot Actuator, Micrometer |
| Demo service | Java 25, Spring Boot 4, Maven Wrapper |
| Testing | pytest, Vitest, Testing Library, Playwright, JUnit |
| Code quality | Ruff, mypy, ESLint, Prettier |
| Build and runtime | uv, Docker, Docker Compose, Nginx |
| CI | GitHub Actions |

Only implemented technologies are listed here. Planned capabilities are described in the
[roadmap](#roadmap).

## Current capabilities

- FastAPI endpoints for health checks and investigation requests.
- Optional PostgreSQL snapshots with UUID retrieval and explicit schema migrations.
- Investigation history with service/environment/creation-date filters, cursor pagination,
  and shareable saved-report pages that survive a browser refresh.
- Validated service, environment, and timezone-aware investigation windows.
- JSONL collection filtered by service, environment, and time.
- Log evidence with references to physical lines in the source file.
- Historical Prometheus evidence filtered by service, environment, and time.
- Metric summaries with query references, sample counts, minimum, maximum, and last values.
- Current Actuator info and health snapshots after service/environment identity checks.
- Snapshot timestamps recorded when each response is retrieved, distinct from the incident window.
- Partial collection with explicit reporting of unavailable data and limits.
- Optional structured LLM analysis with evidence-reference validation.
- Evidence-preserving fallback when analysis fails or is rejected.
- A Spring Boot demo service with normal and payment-timeout modes.
- A React and TypeScript UI for submitting investigations and reviewing reports.
- Docker images and a four-service Docker Compose demo, with an optional
  PostgreSQL service and a one-shot migration service in the persistence overlay.
- Python and frontend tests, Java API tests, and telemetry integration checks.
- An opt-in LLM evaluation runner with repeatable scenarios, run metadata, and checkpoints.
- Offline validation of separately recorded manual reviews of saved model outputs.

With analysis disabled, reports contain evidence and data gaps, with empty findings and
hypotheses. A structurally valid model report does not prove that its explanation is
correct.

## Try the MVP

Start with the [Docker Compose quick start](#quick-start-with-docker-compose). The
default demo runs locally without an OpenAI API key. Create a controlled payment
timeout, investigate it in the UI, inspect evidence and data gaps, and export the report
as JSON.

- [Demo walkthrough and recording](docs/demo.md)
- [Validation record and real-model evaluation limits](docs/validation/2026-10-16.md)
- [Release notes for v0.1.0](docs/releases/v0.1.0.md)
- [GitHub release guide](docs/releasing.md)

## Recorded demo

https://github.com/user-attachments/assets/97f5b7a0-0500-4a67-9961-c598e60c685a

[Download the MP4](https://github.com/woody-ai-dev/ai-incident-investigator/releases/download/v0.1.0/mvp-demo.mp4) — 1:22, Full HD 16:9,
English captions. This edited walkthrough uses real browser footage and an unedited
model response on synthetic telemetry. Idle time and repetitive navigation are removed;
close-ups and labelled excerpts explain the evidence. The captions identify remaining
model interpretation errors; this assistant requires engineering review of its
conclusions. The
[full captioned recording](https://github.com/woody-ai-dev/ai-incident-investigator/raw/refs/tags/v0.1.0/docs/assets/mvp-demo-full.mp4) (1:55) is also available.
See the
[actual exported report](docs/validation/live-ui-2026-10-16.json) and
[validation notes](docs/validation/2026-10-16.md#fresh-ui-investigation).

## Architecture

![Current architecture: on-demand investigation, telemetry sources, optional analysis, history and PostgreSQL snapshots](docs/architecture/architecture.svg)

[Editable draw.io diagram](docs/architecture/architecture.drawio)

The investigator reads the shared log file, queries the Prometheus HTTP API, and
retrieves Actuator context when an investigation is requested and those sources are
configured. Prometheus scrapes the Java service every five seconds independently of
investigation requests. Actuator is queried directly and returns current snapshots
rather than historical incident observations.

The metrics collector uses three fixed queries. HTTP clients cannot supply arbitrary
PromQL or select a Prometheus server in the investigation payload. The server address
comes from application configuration. Actuator has one configured service/environment
target; the request cannot select its URL.

The services run as separate processes and share a telemetry contract. The demo payment
gateway is a simulation; there is no external payment provider or order database.
Optional PostgreSQL storage belongs to the investigator and saves completed
investigation snapshots, not orders.

The HTTP route delegates to `execute_investigation()`, an application workflow that
calls the core `investigate()` pipeline and then optionally saves a snapshot through a
storage port. SQLAlchemy and Psycopg implement that port; the application workflow is
independent of FastAPI, SQLAlchemy, and OpenAI. Its short database transaction completes
before the response includes `X-Investigation-ID`; no database session is held during
source collection or LLM calls. Alembic migrations run before application startup. The
evaluation runner bypasses this workflow, calls `investigate()` directly, and keeps
artifacts in files.

## Saved investigations

Enable the optional PostgreSQL store using the
[persistence setup guide](docs/persistence.md#run-the-compose-demo-with-persistence).

Open **Investigations** in the sidebar to browse saved reports. Filter by exact service
and environment names and by creation time; dates use your browser timezone. Older
results use cursor pagination. Select **Open report** to inspect the original evidence,
analysis, data gaps, configured model, prompt hash, and execution duration. **Copy report
link** creates a direct URL that can be reopened after a refresh.

A new report includes an **Open saved investigation** link when persistence succeeds.
The POST response keeps its report JSON and adds `X-Investigation-ID` after commit.
`GET /investigations` lists summaries; `GET /investigations/{id}` retrieves a full
snapshot. These reads never collect sources or call a model. Without PostgreSQL, new
investigations still work and the history page explains that storage is unavailable.
See [history and API details](docs/persistence.md#browse-history-in-the-ui).

## Quick start with Docker Compose

Requirements:

- Docker Engine with Docker Compose, or Docker Desktop.
- A running Docker daemon.
- Network access for the first image build and dependency downloads.
- Ports 3000, 8000, 8081, and 9090 available on the host.

Run commands from the repository root:

```bash
docker compose config --quiet
docker compose up --build --wait --wait-timeout 180
```

The first command validates the configuration. The second builds the images, starts the
services, and waits for their health checks.

| Service | Address |
| --- | --- |
| Investigator health | [GET /health](http://127.0.0.1:8000/health) |
| Investigation UI | [Local interface](http://127.0.0.1:3000) |
| Investigator API documentation | [Swagger UI](http://127.0.0.1:8000/docs) |
| Order-service health | [GET /actuator/health](http://127.0.0.1:8081/actuator/health) |
| Order-service identity | [GET /actuator/info](http://127.0.0.1:8081/actuator/info) |
| Order creation | `POST http://127.0.0.1:8081/api/v1/orders` |
| Java metrics exporter | [GET /actuator/prometheus](http://127.0.0.1:8081/actuator/prometheus) |
| Prometheus interface | [Prometheus UI](http://127.0.0.1:9090) |

The Compose demo enables metric collection with `PROMETHEUS_URL=http://prometheus:9090`
and Actuator collection with `ACTUATOR_URL=http://order-service:8081/actuator/`,
`ACTUATOR_SERVICE=order-service`, and `ACTUATOR_ENVIRONMENT=local` in the investigator's
environment. It explicitly disables LLM analysis and requires no API key. The host does
not need a JDK to run the container demo; the Java image includes the required build and
runtime environments. Host-side check scripts require uv.

Generate a controlled timeout and verify that its evidence reaches the report:

```bash
uv python install
uv sync --locked --dev
uv run --locked python scripts/check_compose_demo.py
```

Use the UI to investigate `order-service` / `local` in the recent time window. For
metrics, Actuator, manual API calls, shutdown, and troubleshooting, see
[demo operations](docs/demo-operations.md) and [source configuration](docs/sources.md).

## Repository structure

```text
src/ai_incident_investigator/
  main.py                          create_app(), lifespan, ASGI app
  dependencies.py                  HTTP dependency/provider wiring
  investigations/
    router.py                      HTTP input, status codes, response headers
    workflow.py                    execute_investigation(): pipeline then save
    service.py                     investigate(): collection and analysis core
    ports.py                       InvestigationStore and StorageError
    records.py                     StoredInvestigation snapshot contract
    schemas.py, reports.py         Request and report contracts
  sources/                         JSONL, Prometheus, and Actuator adapters
  llm/                             OpenAI adapter, prompts, response schema
  storage/                         SQLAlchemy models, engine, repository adapter
frontend/src/
  components/                      Shared controls and branding
  features/investigations/          Form, SourceFlow, report, hooks, styles, tests
migrations/                        Alembic schema migrations
alembic.ini                        Migration environment configuration
tests/                             Python contracts, core, source, and API tests
  storage/                         Persistence tests and scoped database fixtures
evals/                             Synthetic datasets and review rubric
scripts/                           Demo, persistence, and evaluation checks
  check_investigation_storage.py   Saved-snapshot API smoke check
docs/                              Setup guides, architecture, validation, releases
compose.yaml                       Four-service offline demo
compose.persistence.yaml           Optional PostgreSQL and migration service
compose.llm.yaml                   Opt-in live model override
Dockerfile, .dockerignore           Python image and build context
.github/workflows/ci.yaml           Python, storage, Java, frontend, Compose checks
observability/prometheus/           Prometheus scrape configuration
demo-services/order-service/       Java demo and container image
examples/logs.jsonl                 Synthetic example logs
.env.example                       Configuration template without secrets
data/                              Runtime artifacts, excluded from Git
```

## Local development

Install the Python environment and start the API without model calls:

```bash
uv python install
uv sync --locked --dev
LLM_ENABLED=false uv run --locked uvicorn ai_incident_investigator.main:app --reload
```

The import path remains `main:app`; `create_app()` constructs independent app instances
for tests. `DATABASE_URL` is optional. If it is configured, apply
[migrations](docs/persistence.md#run-the-backend-locally) before startup.
See [backend and Java development](docs/development.md) for JDK selection, builds,
captured incidents, and the full local workflow.

For React development and browser checks, see [UI development](docs/ui-development.md).

## Checks and CI

```bash
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy
uv run --locked pytest

npm --prefix frontend run format:check
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
```

Ordinary tests and CI do not call a live model. CI covers Python, PostgreSQL, Java,
frontend/browser checks, and the container demo. PostgreSQL tests require a dedicated
test database; without it, those cases are skipped locally. See [CI
details](docs/development.md#checks-and-ci),
[persistence tests](docs/persistence.md#test-databases),
[browser checks](docs/ui-development.md#browser-end-to-end-checks), and
[offline/live evaluation](docs/pipeline-evaluation.md).

## Current limits

The assistant runs on request and does not monitor services autonomously. Telemetry is
limited to one JSONL source, three fixed Prometheus queries, and one configured Actuator
target. Actuator reports current state; metric counters are cumulative, and scrape
success does not establish business health.

Model output still requires engineering review. Saved history and shareable report
pages require optional PostgreSQL storage. Without it, the workspace keeps its latest
report only in memory. Queues, traces, RAG, automated fixes, and notifications are not
implemented. See [all collection and analysis limits](docs/limitations.md) and the
[real-model validation record](docs/validation/2026-10-18-analysis-boundaries.md).

## Guides

Detailed commands and limits live in the guides below. Existing section links continue
to point to the matching guide.

| Guide | Contents |
| --- | --- |
| <a id="check-the-log-investigation-demo"></a>[Check the log investigation demo](docs/demo-operations.md#check-the-log-investigation-demo) | Container demo and telemetry checks |
| <a id="check-the-prometheus-demo"></a>[Check the Prometheus demo](docs/demo-operations.md#check-the-prometheus-demo) | Container demo and telemetry checks |
| <a id="check-logs-and-metrics-in-one-investigation"></a>[Check logs and metrics in one investigation](docs/demo-operations.md#check-logs-and-metrics-in-one-investigation) | Container demo and telemetry checks |
| <a id="metric-evidence-semantics"></a>[Metric evidence semantics](docs/demo-operations.md#metric-evidence-semantics) | Container demo and telemetry checks |
| <a id="reproduce-the-timeout-manually"></a>[Reproduce the timeout manually](docs/demo-operations.md#reproduce-the-timeout-manually) | Container demo and telemetry checks |
| <a id="container-design"></a>[Container design](docs/demo-operations.md#container-design) | Container demo and telemetry checks |
| <a id="stop-the-demo"></a>[Stop the demo](docs/demo-operations.md#stop-the-demo) | Container demo and telemetry checks |
| <a id="troubleshooting"></a>[Troubleshooting](docs/demo-operations.md#troubleshooting) | Container demo and telemetry checks |
| <a id="capture-a-local-incident"></a>[Capture a local incident](docs/development.md#capture-a-local-incident) | Backend and Java development |
| <a id="prometheus-configuration"></a>[Prometheus configuration](docs/sources.md#prometheus-configuration) | Source setup and observation boundaries |
| <a id="spring-boot-actuator-context"></a>[Spring Boot Actuator context](docs/sources.md#spring-boot-actuator-context) | Source setup and observation boundaries |
| <a id="optional-llm-analysis"></a>[Optional LLM analysis](docs/llm-analysis.md#optional-llm-analysis) | Opt-in setup, statuses, and validation |
| <a id="investigation-ui"></a>[Investigation UI](docs/ui-development.md#investigation-ui) | UI behavior, frontend development, and browser checks |
| <a id="browser-end-to-end-checks"></a>[Browser end-to-end checks](docs/ui-development.md#browser-end-to-end-checks) | UI behavior, frontend development, and browser checks |
| <a id="offline-investigation-evaluation"></a>[Offline investigation evaluation](docs/pipeline-evaluation.md#offline-investigation-evaluation) | Offline contracts and opt-in model evaluation |
| <a id="optional-live-llm-evaluation"></a>[Optional live LLM evaluation](docs/pipeline-evaluation.md#optional-live-llm-evaluation) | Offline contracts and opt-in model evaluation |
| [Saved investigations](docs/persistence.md) | PostgreSQL, migrations, API, metadata, and tests |
| [Analysis boundaries](docs/analysis-boundaries.md) | Evidence IDs, temporal support, and metric interpretation |
| [Model evaluation procedure](docs/llm-evaluation.md) | Live run artifacts, review, and release checks |
| [Demo recording](docs/demo.md) | Walkthrough and opt-in recording procedure |
| [Release guide](docs/releasing.md) | Versioning and GitHub publication |

## Roadmap

Next steps include more detailed source statuses and collection timing, token/cost
accounting, and broader evaluation. Metric interpretation still needs repeated checks
on unseen incidents;
current validation records document remaining errors.

Later work may add centralized telemetry, traces, background jobs, alert-triggered
investigations, and retrieval of operational knowledge. A remediation stage would
reproduce bugs in an isolated checkout, validate candidate patches, and open pull
requests for human review. These capabilities are planned. See the [release
guide](docs/releasing.md) for release preparation.
