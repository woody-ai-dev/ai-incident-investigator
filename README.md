# AI Incident Investigator

An incident investigation assistant in development, intended to help on-call
engineers and SREs turn service telemetry into evidence-backed incident reports.

The current version collects evidence from JSONL logs and optionally uses OpenAI
for structured analysis. A Java demo service generates a reproducible
payment-timeout scenario, and Prometheus collects its HTTP and JVM metrics.
Investigation reports currently use logs only; Prometheus evidence collection
is the next integration step. Automated remediation is not implemented.

## Current capabilities

- FastAPI endpoints for health checks and investigation requests.
- Validated service, environment, and timezone-aware investigation windows.
- JSONL collection filtered by service, environment, and time.
- Evidence with references to physical lines in the source file.
- Explicit reporting of unavailable data and collection limits.
- Optional structured LLM analysis with evidence-reference validation.
- Evidence-preserving fallback when analysis fails or is rejected.
- A Spring Boot demo service with normal and payment-timeout modes.
- Docker images and a three-service Docker Compose demo.
- Prometheus scraping with service and environment labels.
- Python tests, Java API tests, and end-to-end checks for logs and metrics.

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

A separate metrics path runs alongside the investigation path:

```text
Java order-service
    -> /actuator/prometheus
    -> Prometheus scrapes every 5 seconds
    -> time series in the prometheus-data volume
    -> Prometheus API and metrics demo check
```

The investigator does not yet query the Prometheus API. The metrics demo check
validates collection separately from the log-based investigation report.

The services run as separate processes and share a telemetry contract.
The demo payment gateway is a simulation; there is no external payment provider
or order database.

## Quick start with Docker Compose

Requirements:

- Docker Engine with Docker Compose, or Docker Desktop.
- A running Docker daemon.
- Network access for the first image build and dependency downloads.
- Ports 8000, 8081, and 9090 available on the host.

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
| Java metrics exporter | http://127.0.0.1:8081/actuator/prometheus |
| Prometheus interface | http://127.0.0.1:9090 |

The Compose demo explicitly disables LLM analysis and requires no API key.
The host does not need a JDK to run the container demo; the Java image includes
the required build and runtime environments. Host-side check scripts require uv.

## Check the log investigation demo

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

## Check the Prometheus demo

Prometheus reads `observability/prometheus/prometheus.yaml`, mounted into its
container as `/etc/prometheus/prometheus.yml`. It scrapes the Java service every
five seconds and retains metrics for 24 hours in the `prometheus-data` volume.

Validate the running Prometheus configuration and check metrics collection:

```bash
docker compose exec -T prometheus \
  /bin/promtool check config /etc/prometheus/prometheus.yml

uv run --locked python scripts/check_prometheus_demo.py
```

The metrics check:

1. Checks that the Java metrics endpoint is reachable.
2. Waits for a fresh scrape, avoiding data left over from a previous run.
3. Requires the order-service target to report `up = 1`.
4. Requires JVM heap memory metrics.
5. Creates an order and expects HTTP 504 with `PAYMENT_TIMEOUT` and an order ID.
6. Waits for the HTTP 504 request counter to increase.

An example successful result:

```text
Prometheus demo passed: order=<UUID>; http_504_count=1->2; heap_bytes=<number>.
```

Counter and memory values vary between runs. The counter represents aggregated
requests. Order IDs remain in logs and are not added as metric labels.
The check assumes the Java service is not restarted while it runs.

Open the Prometheus interface and try these queries:

```promql
up{service="order-service",environment="local"}
```

```promql
sum(
  http_server_requests_seconds_count{
    service="order-service",
    environment="local",
    uri="/api/v1/orders",
    method="POST",
    status="504"
  }
)
```

```promql
sum(
  jvm_memory_used_bytes{
    service="order-service",
    environment="local",
    area="heap"
  }
)
```

`up = 1` means scraping succeeded; a business operation can still fail.
The `_count` series measures completed requests, while the heap gauge is in bytes.
An empty result means no matching series are available, not necessarily zero
failures. Both demo checks can run without live LLM analysis.

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
- Prometheus runs as the image's non-root user and stores metrics in its own volume.
- Its configuration is mounted read-only; a missing source file stops startup.
- Root filesystems are read-only; /tmp is a temporary filesystem.
- Host ports are bound to 127.0.0.1.
- The investigator and Prometheus start after the Java health check succeeds.
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

Stop the services while retaining captured logs and metrics:

```bash
docker compose down
```

For a fresh capture, remove both demo volumes:

```bash
docker compose down --volumes
```

The last command deletes captured logs and stored Prometheus metrics.
Reading logs from Python does not delete or consume them. Java continues
appending to the active log file and rotates it according to its Logback
configuration. The investigator currently reads only the active file.

## Repository structure

```text
Dockerfile                         Python image
.dockerignore                      Python build context exclusions
compose.yaml                       Local container demo
.github/workflows/ci.yaml           CI checks
src/ai_incident_investigator/       API, models, collection, and analysis
tests/                             Python tests
scripts/check_compose_demo.py       Container log investigation check
scripts/check_prometheus_demo.py    Prometheus collection check
scripts/check_demo_logs.py          Java-to-Python log contract check
observability/prometheus/           Prometheus scrape configuration
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

On macOS, select JDK 25 in each terminal that builds or runs the Java service:

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 25)
export PATH="$JAVA_HOME/bin:$PATH"
```

These exports apply to the current terminal session. Confirm the JDK used by Maven:

```bash
./demo-services/order-service/mvnw -version
```

The output should report Java 25. The POM's `java.version` sets the compilation
target; it does not select the JDK that launches Maven. Use the same JDK 25
as CI and the Java container image.

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
- Docker image builds, Prometheus configuration validation, and both demo checks.

Python tests disable live analysis. Adapter tests use mocked HTTP responses.
CI requires no OpenAI API key.

The Docker job removes its temporary containers, log volume, and metrics volume
after the checks.

## Current limits

- Investigations run on request and collect one local JSONL source.
- There is no continuous incident detection or service discovery.
- At most 100 evidence records, 5 MiB scanned, and 64 KiB per line by default.
- Malformed records and collection limits are reported as data gaps.
- Rotated log archives are not collected automatically.
- Line references apply to the source file used for that investigation.
- Prometheus stores demo metrics, but the investigator does not yet collect metric evidence.
- Distributed traces and Actuator context collection are not connected.
- LLM input JSON is limited to 32,000 UTF-8 bytes, excluding instructions and schema.
- Model output is capped at 2,500 tokens.
- The SDK uses a 20-second timeout and at most one retry.
- Requests use store=False; this does not imply zero provider data retention.
- No persistent investigation history, background workers, or React UI.
- No automatic patch generation, pull requests, deployment, or on-call notifications.

## Troubleshooting

- Docker daemon unavailable: start Docker Desktop or Docker Engine.
- Port already allocated: stop an existing local service using port 8000, 8081, or 9090.
- Container unhealthy: inspect docker compose ps and docker compose logs.
- No matching evidence: check the source file, service, environment, and time window.
- Expected HTTP 504 but received 201: ensure the payment-timeout demo is running.
- Analysis failed: check API access, input limits, and model availability.
- OPENAI_API_KEY is required: load the local .env or disable analysis.
- Java compilation errors, including `ExceptionInInitializerError` / `EndPosTable`:
  run `mvnw -version` and select JDK 25 using the local development commands above.
- Prometheus target down: inspect its Targets page and Java container logs;
  the scrape address inside Docker is `order-service:8081`.
- Metrics check timed out: confirm the target is healthy and that the service
  remains running while the check waits for fresh scrapes.
- Prometheus bind mount missing: ensure
  `observability/prometheus/prometheus.yaml` exists in the checkout.
- Metrics marked unavailable in an investigation report: this is expected
  until the investigator's Prometheus collector is implemented.

## Roadmap

The next milestone is to collect Prometheus evidence in investigation reports.
Subsequent MVP work includes Actuator context, a task-specific evaluation set,
and a React interface. Complete live-model validation before release.

Later work can add centralized log sources, multiple environments, persistent
investigations, background jobs, and investigations triggered by alerts.
A future remediation stage would reproduce selected bugs in an isolated
checkout, validate candidate patches, and open pull requests for human review.
These capabilities are planned and are not part of the current implementation.