# AI Incident Investigator

An incident investigation assistant in development, intended to help on-call
engineers and SREs turn service telemetry into evidence-backed incident reports.

The current version collects evidence from local JSONL logs. A Java demo service
produces a reproducible payment-timeout scenario. LLM analysis is the next
milestone; root-cause inference and automated remediation are not implemented.

## What works today

- FastAPI endpoints for health checks and investigation requests.
- Validated service, environment, and timezone-aware investigation windows.
- JSONL collection filtered by service, environment, and time.
- Evidence with references to physical lines in the configured log file.
- Explicit reporting of unavailable data, malformed records, and collection limits.
- A Spring Boot order service with normal and simulated payment-timeout modes.
- Python tests, Java API tests, and a Java-to-Python log contract check.

An investigation currently returns collected evidence and data gaps. Its
`findings` and `hypotheses` lists remain empty, and it does not identify a root cause.

## Architecture

```text
HTTP order request
    -> Java order-service
    -> JSONL log file
    -> Python log collector
    -> validated InvestigationReport
```

The applications run as separate processes. They share a telemetry contract,
not implementation code. The Java demo uses a `PaymentGateway` interface backed
by a simulation; there is no external payment service or database yet.

```text
.github/workflows/ci.yaml          CI checks
src/ai_incident_investigator/      Python API, report models, and log collector
tests/                            Python tests
scripts/check_demo_logs.py        Java log contract check
examples/logs.jsonl                Synthetic example logs
demo-services/order-service/      Standalone Java/Maven application
data/                             Local runtime data, excluded from Git
```

## Requirements

- `uv` and Python 3.12, installed through `uv`.
- JDK 25 for the Java application.
- Network access for the initial dependency downloads.

Maven 3.9.16 is provided through the committed Maven Wrapper. A separate Maven
installation is not required. The shell examples below use a POSIX shell.

Run commands from the repository root unless stated otherwise.

## Setup

```bash
uv python install
uv sync --locked --dev
```

Select JDK 25 in the terminal used for the Java build. On macOS:

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 25)
export PATH="$JAVA_HOME/bin:$PATH"
```

On other systems, set `JAVA_HOME` to the installed JDK 25 directory.
Verify the JDK Maven actually uses:

```bash
./demo-services/order-service/mvnw -version
```

The output must show Java 25. The `java.version` property in `pom.xml` does not
select the JDK that runs Maven. Repeat the environment setup in a new terminal.

## Build and test

Build the Java application and run its six API tests:

```bash
./demo-services/order-service/mvnw \
  -f demo-services/order-service/pom.xml -B -ntp clean verify
```

Validate the generated timeout logs against the Python model:

```bash
uv run --locked python scripts/check_demo_logs.py \
  demo-services/order-service/target/test-logs/timeout.jsonl
```

The check must report valid records and a simulated timeout. The record count
can vary with framework logging.

Run Python checks:

```bash
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy
uv run --locked pytest
```

The GitHub Actions workflow runs Python checks, the Java build, and the log
contract check on pull requests and pushes to `main`.

## Reproduce an incident

### 1. Start the Java service

After building the JAR, run this in terminal A:

```bash
mkdir -p data

DEMO_PAYMENT_MODE=payment-timeout \
DEMO_LOG_FILE="$PWD/data/order-service-timeout.jsonl" \
java -jar demo-services/order-service/target/order-service-0.1.0.jar
```

In terminal B, check readiness and submit an order:

```bash
curl -i http://127.0.0.1:8081/actuator/health

curl -i http://127.0.0.1:8081/api/v1/orders \
  -H 'Content-Type: application/json' \
  -d '{"productId":"book-1","quantity":2}'
```

Health returns `200` with `status: UP`. The order request returns `504` with
`code: PAYMENT_TIMEOUT` and an `orderId`. The file contains an `ERROR` event
with `Payment request timed out (simulated)` in its message.

This mode throws a controlled exception immediately. It does not reproduce an
actual network delay. Health remains UP because the application itself is running.

For the success scenario, restart with `DEMO_PAYMENT_MODE=normal` and a different
log filename. A valid order returns `201` with `status: ACCEPTED`. Missing or
invalid quantities return `400`. Orders are not persisted.

### 2. Start the investigator

Stop the Java service with `Ctrl+C` after reproducing the error. Use the completed
file as a snapshot for the current collector. In terminal A, run:

```bash
INVESTIGATOR_LOG_PATH="$PWD/data/order-service-timeout.jsonl" \
uv run --locked uvicorn ai_incident_investigator.main:app --reload
```

- API documentation: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health
- Investigation endpoint: `POST /investigations`

### 3. Investigate the captured time window

In terminal B, generate a request using timestamps from the actual file. This
avoids accidentally investigating an interval after the incident:

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
Path("data/investigation-request.json").write_text(json.dumps(request, indent=2))
PY

curl -i http://127.0.0.1:8000/investigations \
  -H 'Content-Type: application/json' \
  --data-binary @data/investigation-request.json
```

The report should contain log evidence, including the simulated timeout, with
references such as `local-jsonl:line:14`. Other telemetry sources remain listed
in `missing_data`.

An HTTP `200` means a report was produced, not that a root cause was established.
A missing file can also produce a report with a data-gap explanation.

Log files append across repeated runs. The example above covers all timestamps
in the selected file; use a fresh filename for an isolated capture.

## Configuration

| Variable | Application | Default | Purpose |
| --- | --- | --- | --- |
| `INVESTIGATOR_LOG_PATH` | Python | `data/logs.jsonl` | JSONL file to investigate |
| `DEMO_PAYMENT_MODE` | Java | `normal` | `normal` or `payment-timeout` |
| `DEMO_ENVIRONMENT` | Java | `local` | Environment label in logs |
| `DEMO_LOG_FILE` | Java | `logs/order-service.jsonl` | Output log file |

Relative paths are resolved against the process working directory. The Python
settings code reads process environment variables; it does not automatically load
an `.env` file.

Investigation windows include the start and exclude the end:
`start_time <= timestamp < end_time`. Timestamps require a timezone and are
normalized to UTC. For example, `19:40Z` and `22:40+03:00` describe the same time.

## Current limits

- One local JSONL source, read in file order.
- At most 100 evidence records, 5 MiB scanned, and 64 KiB per line by default.
- Malformed records are skipped and reported; byte limits can stop collection.
- A line reference is meaningful only for the captured file; rotated archives
  and changing files are not handled as a persistent evidence store.
- Prometheus metrics, distributed traces, and Actuator context collection are
  not connected. The Java Actuator health endpoint is available independently.
- No LLM analysis, persistent investigation history, React UI, or automatic fixes.

## Troubleshooting

- **`EndPosTable` during Java compilation:** check `mvnw -version` and select JDK 25.
  This project has been verified on JDK 25.
- **No matching log records:** check the configured file, service, environment,
  and time window. A window starting after the incident excludes its records.
- **`mvnw: No such file or directory` in CI:** commit `mvnw`, `mvnw.cmd`, and
  `.mvn/wrapper/maven-wrapper.properties`. Keep `mvnw` executable.
- **Maven Central network errors:** restore network/proxy access, then retry with
  `-U`. A download failure is separate from a compilation error.

## Next milestone

Add LLM analysis over collected evidence, with structured output validation,
checks that evidence references exist, bounded requests, and explicit handling
of model failures. Evaluate timeout, successful-request, and missing-data cases
before expanding to additional telemetry sources.
