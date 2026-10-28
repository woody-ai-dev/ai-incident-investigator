# Backend and Java development

Run commands from the repository root unless stated otherwise. For the container demo,
use the [quick start](../README.md#quick-start-with-docker-compose); for database setup,
see [persistence](persistence.md).

## Local development

For development without containers, install uv and JDK 25. Maven 3.9.16 is provided
through the committed Maven Wrapper.

```bash
uv python install
uv sync --locked --dev
```

On macOS, select JDK 25 in each terminal that builds or runs the Java service:

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 25)
export PATH="$JAVA_HOME/bin:$PATH"
```

These exports apply to the current terminal session. Confirm the JDK used by Maven:

```bash
./demo-services/order-service/mvnw -version
```

The output should report Java 25. The POM's `java.version` sets the compilation target;
it does not select the JDK that launches Maven. Use the same JDK 25 as CI and the Java
container image.

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

Stop Java with Ctrl+C after capturing the error. Start the investigator in terminal A:

```bash
LLM_ENABLED=false \
DATABASE_URL= \
PROMETHEUS_URL= \
ACTUATOR_URL= \
ACTUATOR_SERVICE= \
ACTUATOR_ENVIRONMENT= \
INVESTIGATOR_LOG_PATH="$PWD/data/order-service-timeout.jsonl" \
uv run --locked uvicorn ai_incident_investigator.main:app --reload
```

This capture uses logs only and disables optional persistence with an empty
`DATABASE_URL`. Empty `PROMETHEUS_URL` and all three empty `ACTUATOR_*` variables
explicitly disable the HTTP sources for this local run, even if the terminal previously
exported their configuration.

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

For the success scenario, restart Java with DEMO_PAYMENT_MODE=normal and a fresh log
filename. A valid order returns HTTP 201 with status ACCEPTED. Orders are not persisted.

## Checks and CI

The [CI badge in the README](../README.md) follows push runs on `main`. The workflow
covers Python, frontend, Java, and Docker Compose checks. Pull requests run the same
workflow before merge; open the badge to inspect individual job results.

Run Python checks:

```bash
uv sync --locked --dev --extra ingestion --extra retrieval
uv run --locked --extra ingestion --extra retrieval ruff format --check .
uv run --locked --extra ingestion --extra retrieval ruff check .
uv run --locked --extra ingestion --extra retrieval mypy
uv run --locked --extra ingestion --extra retrieval pytest
```

The optional `ingestion` dependencies enable offline HTML/PDF conversion tests.
The `retrieval` extra enables Qdrant tests. Full type checking requires both extras.
The normal API and Markdown ingestion use the base environment. Conversion tests
read committed fixtures and do not download models or access the network; see the
[knowledge ingestion guide](knowledge.md).

GitHub Actions runs these validation jobs on pull requests and pushes to main:

- Python formatting, linting, type checks, tests including offline document
  conversion, and coverage reports.
- Gitleaks scanning of the full Git history with redacted findings.
- PostgreSQL integration tests using a dedicated database and per-test schemas.
- Qdrant server contract tests using deterministic fixture vectors and a dedicated service.
- Java tests and the Java-to-Python log contract check.
- Frontend formatting, linting, component and browser tests, E2E type checks, and production builds.
- Docker image builds, Prometheus configuration validation, all four telemetry
  demo checks, a repeated log investigation through the frontend API proxy, a browser smoke test, and an offline persistence-overlay check.

Python tests disable live analysis and remove the database URL, Prometheus URL, and all
three Actuator configuration variables by default. Storage-specific fixtures and
adapter/API tests live under `tests/storage/`. Set `TEST_DATABASE_URL` only for an
isolated PostgreSQL test database, as described in [persistence
testing](persistence.md#test-databases). Adapter tests use mocked HTTP responses. They
cover missing data, partial failures, invalid and oversized responses, label escaping,
time boundaries, and the integration of logs and metrics into an API report. Actuator
tests cover identity mismatches, current snapshot timestamps, HTTP 503 health, field
filtering, and partial collection failures. CI requires no OpenAI API key.

The Docker job removes its temporary containers, telemetry volumes, and investigation
database volume after the checks.

Successful Python checks and secret scanning on `main` also publish the Python coverage
badge to a separate `coverage-badges` branch. The publication job uses GitHub's automatic
token; no user API keys or external coverage service are required. See
[CI security and coverage setup](ci-security.md) for permissions and repository settings.
