# AI Incident Investigator

An incident investigation assistant in development, intended to help on-call
engineers and SREs turn service telemetry into evidence-backed incident reports.

The current version collects evidence from JSONL logs and optionally uses OpenAI
for structured analysis. A Java demo service generates a reproducible
payment-timeout scenario. Automated remediation is not implemented.

## Current capabilities

- FastAPI endpoints for health checks and investigation requests.
- Validated service, environment, and timezone-aware investigation windows.
- JSONL collection filtered by service, environment, and time.
- Evidence with references to physical lines in the source file.
- Explicit reporting of unavailable data and collection limits.
- Optional structured LLM analysis with evidence-reference validation.
- Evidence-preserving fallback when analysis fails or is rejected.
- A Spring Boot demo service with normal and payment-timeout modes.
- Docker images and a Docker Compose demo.
- Python tests, Java API tests, and an end-to-end demo check.

With analysis disabled, reports contain evidence and data gaps, with empty
findings and hypotheses. A structurally valid model report does not prove that
its explanation is correct.

## Architecture

```text
Order request
    -> Java order-service
    -> JSONL file in the shared log volume
    -> Python log collector
    -> evidence and data gaps
    -> optional OpenAI analysis
    -> output and evidence-reference validation
    -> InvestigationReport
```

The services run as separate processes and share a telemetry contract.
The demo payment gateway is a simulation; there is no external payment provider
or order database.

## Quick start with Docker Compose

Requirements:

- Docker Engine with Docker Compose, or Docker Desktop.
- A running Docker daemon.
- Network access for the first image build and dependency downloads.
- Ports 8000 and 8081 available on the host.

Run commands from the repository root:

```bash
docker compose config --quiet
docker compose up --build --wait --wait-timeout 180
```

The first command validates the configuration. The second builds the images,
starts the services, and waits for their health checks.

| Service | Address |
| --- | --- |
| Investigator health | http://127.0.0.1:8000/health |
| Investigator API documentation | http://127.0.0.1:8000/docs |
| Order-service health | http://127.0.0.1:8081/actuator/health |
| Order creation | POST http://127.0.0.1:8081/api/v1/orders |

The Compose demo explicitly disables LLM analysis and requires no API key.

## Check the complete demo

Install the host-side Python environment:

```bash
uv python install
uv sync --locked --dev
```

Run the check against the running Compose services:

```bash
uv run --locked python scripts/check_compose_demo.py
```

The script:

1. Checks both health endpoints.
2. Creates an order and expects HTTP 504 with PAYMENT_TIMEOUT.
3. Uses the returned order ID and a recent UTC time window to investigate.
4. Validates the response against InvestigationReport.
5. Requires timeout evidence for that exact order.
6. Requires analysis_status to be not_requested.

An example successful result:

```text
Compose demo passed: order=<UUID>; evidence=<count>; analysis_status=not_requested.
```

Record counts vary with framework logging and the selected time window.

## Reproduce the timeout manually

```bash
curl -i http://127.0.0.1:8081/api/v1/orders \
  -H 'Content-Type: application/json' \
  -d '{"productId":"book-1","quantity":2}'
```

The response should be HTTP 504 with code PAYMENT_TIMEOUT and an orderId.
Health remains UP because the application itself is running.

The simulation throws a controlled exception immediately. It does not reproduce
an actual network delay or explain why a real dependency would be slow.

## Container design

- Python dependencies are installed from uv.lock without development packages.
- The Python application is installed in non-editable mode.
- Java is built with Maven Wrapper and JDK 25, then runs in a JRE image.
- Both applications run as a non-root user with UID 10001.
- Java writes logs to the named demo-logs volume.
- Python mounts the same volume read-only.
- Root filesystems are read-only; /tmp is a temporary filesystem.
- Host ports are bound to 127.0.0.1.
- The investigator starts after the Java health check succeeds.
- LLM_ENABLED is explicitly false in Compose.
- OPENAI_API_KEY is not passed to the containers.
- Docker build contexts include only the files required for each image.

Inside containers, both HTTP servers listen on 0.0.0.0.
This allows Docker's published ports to reach them.

The Compose configuration uses /data/order-service.jsonl for both the Java log
destination and the Python log source.

## Stop the demo

Inspect services and logs:

```bash
docker compose ps
docker compose logs --tail=100
```

Stop the services while retaining captured logs:

```bash
docker compose down
```

For a fresh capture, remove the demo volume:

```bash
docker compose down --volumes
```

The last command deletes the saved logs from the Compose volume.

## Repository structure

```text
Dockerfile                         Python image
.dockerignore                      Python build context exclusions
compose.yaml                       Local container demo
.github/workflows/ci.yaml           CI checks
src/ai_incident_investigator/       API, models, collection, and analysis
tests/                             Python tests
scripts/check_compose_demo.py      Container demo check
scripts/check_demo_logs.py         Java-to-Python log contract check
examples/logs.jsonl                 Synthetic example logs
demo-services/order-service/       Java application and its Docker image
.env.example                       Configuration template without secrets
data/                              Local runtime data, excluded from Git
```

## Local development

For development without containers, install uv and JDK 25.
Maven 3.9.16 is provided through the committed Maven Wrapper.

```bash
uv python install
uv sync --locked --dev
```

On macOS, select JDK 25 for the terminal:

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 25)
export PATH="$JAVA_HOME/bin:$PATH"
```

Confirm the JDK used by Maven:

```bash
./demo-services/order-service/mvnw -version
```

Build and test the Java service:

```bash
./demo-services/order-service/mvnw \
  -f demo-services/order-service/pom.xml -B -ntp clean verify
```

Validate its generated timeout logs:

```bash
uv run --locked python scripts/check_demo_logs.py \
  demo-services/order-service/target/test-logs/timeout.jsonl
```

Stop Compose before starting local services on the same ports.

## Capture a local incident

Start the Java service in terminal A:

```bash
mkdir -p data

DEMO_PAYMENT_MODE=payment-timeout \
DEMO_LOG_FILE="$PWD/data/order-service-timeout.jsonl" \
java -jar demo-services/order-service/target/order-service-0.1.0.jar
```

Create an order in terminal B:

```bash
curl -i http://127.0.0.1:8081/api/v1/orders \
  -H 'Content-Type: application/json' \
  -d '{"productId":"book-1","quantity":2}'
```

Stop Java with Ctrl+C after capturing the error. Start the investigator in
terminal A:

```bash
LLM_ENABLED=false \
INVESTIGATOR_LOG_PATH="$PWD/data/order-service-timeout.jsonl" \
uv run --locked uvicorn ai_incident_investigator.main:app --reload
```

Generate a request from the captured timestamps in terminal B:

```bash
uv run --locked python - <<'PY'
import json
from datetime import datetime, timedelta
from pathlib import Path

path = Path("data/order-service-timeout.jsonl")
records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
timestamps = [datetime.fromisoformat(record["timestamp"]) for record in records]

request = {
    "service": "order-service",
    "environment": "local",
    "start_time": min(timestamps).isoformat(),
    "end_time": (max(timestamps) + timedelta(seconds=1)).isoformat(),
    "description": "Order creation returns HTTP 504.",
}

Path("data/investigation-request.json").write_text(
    json.dumps(request, indent=2),
    encoding="utf-8",
)
PY

curl -i http://127.0.0.1:8000/investigations \
  -H 'Content-Type: application/json' \
  --data-binary @data/investigation-request.json
```

For the success scenario, restart Java with DEMO_PAYMENT_MODE=normal and a fresh
log filename. A valid order returns HTTP 201 with status ACCEPTED.
Orders are not persisted.

## Optional LLM analysis

Live analysis is optional. The Compose demo and CI do not use it.

For local live analysis, create a private .env file using .env.example as a
template. Update an existing .env instead of overwriting it.

```dotenv
INVESTIGATOR_LOG_PATH=data/order-service-timeout.jsonl
LLM_ENABLED=true
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=gpt-4.1-mini-2025-04-14
```

Replace the key placeholder with your own API key.
Keep real credentials out of .env.example and Git.

Restart the local investigator with:

```bash
uv run --env-file .env --locked uvicorn ai_incident_investigator.main:app --reload
```

Python settings read process environment variables. They do not automatically
load .env; the command above loads it through uv.

When analysis is enabled, a missing or blank key prevents application startup.
Requests send the investigation request, selected evidence, and data gaps to the
configured model.

| analysis_status | Meaning |
| --- | --- |
| not_requested | LLM analysis is disabled. |
| skipped | Analysis is enabled, but there is no matching evidence. |
| completed | Analysis passed output and evidence-reference validation. |
| failed | Analysis failed or was rejected; evidence has been retained. |

Findings and hypotheses must reference existing evidence IDs.
This checks report structure and references, not the correctness of the reasoning.

## Checks and CI

Run Python checks:

```bash
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy
uv run --locked pytest
```

GitHub Actions runs three jobs on pull requests and pushes to main:

- Python formatting, linting, type checks, and tests.
- Java tests and the Java-to-Python log contract check.
- Docker image builds and the Compose incident check.

Python tests disable live analysis. Adapter tests use mocked HTTP responses.
CI requires no OpenAI API key.

The Docker job removes its temporary containers and log volume after the check.

## Current limits

- One local JSONL source.
- At most 100 evidence records, 5 MiB scanned, and 64 KiB per line by default.
- Malformed records and collection limits are reported as data gaps.
- Rotated log archives are not collected automatically.
- Line references apply to the source file used for that investigation.
- Prometheus, distributed traces, and Actuator context collection are not connected.
- LLM input JSON is limited to 32,000 UTF-8 bytes, excluding instructions and schema.
- Model output is capped at 2,500 tokens.
- The SDK uses a 20-second timeout and at most one retry.
- Requests use store=False; this does not imply zero provider data retention.
- No persistent investigation history, React UI, or automatic remediation.

## Troubleshooting

- Docker daemon unavailable: start Docker Desktop or Docker Engine.
- Port already allocated: stop an existing local service using port 8000 or 8081.
- Container unhealthy: inspect docker compose ps and docker compose logs.
- No matching evidence: check the source file, service, environment, and time window.
- Expected HTTP 504 but received 201: ensure the payment-timeout demo is running.
- Analysis failed: check API access, input limits, and model availability.
- OPENAI_API_KEY is required: load the local .env or disable analysis.
- Java compilation errors: confirm Maven is running with JDK 25.

## Next milestone

Add Prometheus evidence, then Actuator context and a task-specific evaluation set.
Build the React interface as the MVP grows. Complete live-model validation before
release.