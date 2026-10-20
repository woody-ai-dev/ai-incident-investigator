# Demo operations

Start the services with the [Docker Compose quick
start](../README.md#quick-start-with-docker-compose). Run commands from the repository
root unless stated otherwise. The default demo makes no model requests.

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

Evidence counts vary with framework logging, metric and Actuator availability, and the
selected time window. This check requires the created order's log evidence; it does not
require metric or Actuator evidence.

## Check the Prometheus demo

Prometheus reads `observability/prometheus/prometheus.yaml`, mounted into its container
as `/etc/prometheus/prometheus.yml`. It scrapes the Java service every five seconds and
retains metrics for 24 hours in the `prometheus-data` volume.

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

Counter and memory values vary between runs. The counter represents aggregated requests.
Order IDs remain in logs and are not added as metric labels. The check assumes the Java
service is not restarted while it runs.

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

`up = 1` means scraping succeeded; a business operation can still fail. The `_count`
series measures completed requests, while the heap gauge is in bytes. An empty result
means no matching series are available, not necessarily zero failures. All telemetry
demo checks run without live LLM analysis.

## Check logs and metrics in one investigation

Run the integration check against the running Compose services:

```bash
uv run --locked python scripts/check_investigation_metrics.py
```

The script:

1. Creates an order and validates HTTP 504, PAYMENT_TIMEOUT, and the order UUID.
2. Requests an investigation starting 30 seconds before the order was created.
3. Repeats investigation requests with an updated end time while waiting for scrapes.
4. Requires the simulated timeout log for that exact order.
5. Requires `metric-up`, `metric-jvm-heap`, and `metric-http-504-counter` evidence.
6. Requires `analysis_status` to be `not_requested`.

An example successful result:

```text
Investigation metrics demo passed: order=<UUID>; metric_evidence=3; analysis_status=not_requested.
```

The polling budget is 30 seconds; an in-flight HTTP request may extend the elapsed time.
Logs associate the timeout with the order UUID. Metric evidence provides aggregated
service context and does not identify that order. The separate Prometheus check verifies
that a newly generated timeout increases the counter; this integration check verifies
that metrics reach the report.

## Metric evidence semantics

The collector evaluates fixed queries for the requested service and environment:

| Evidence ID | Observation |
| --- | --- |
| `metric-up` | Minimum `up` across observed targets. Zero means at least one observed target failed to scrape. |
| `metric-jvm-heap` | Sum of JVM heap usage in bytes across matching series. |
| `metric-http-504-counter` | Sum of the cumulative HTTP 504 counter for `POST /api/v1/orders`. |

Each evidence item contains the observed sample count, minimum, maximum, last value, and
the full `query_range` URL. The collector summarizes the queried window; it does not
persist the raw time series.

Evaluation uses a five-second step and a fifteen-second lookback, suited to the demo's
five-second scrape interval. Evaluation timestamps are not scrape timestamps: a value
can come from a preceding scrape, including one just before the investigation start.
Query bounds are rounded inward to milliseconds so that evaluation points stay in
`[start_time, end_time)`.

Empty results are reported as missing data rather than converted to zero. HTTP errors,
invalid responses, query annotations, and missing evaluation points are reported in
`missing_data`. Other successfully collected metrics and log evidence are retained.

The HTTP counter is cumulative and may reset when a process restarts. Its value is not
the number of failures during the investigation window. Heap usage alone does not
establish a memory leak, and successful scraping does not establish business health.
Queries aggregate matching targets; they do not prove that all expected instances were
observed. The HTTP query currently targets the order-service demo route rather than
discovering arbitrary application routes.

Query references can be repeated while the data is retained, but they are not immutable
snapshots. Compose references use the internal hostname `prometheus`; when replaying
from the host, replace it with the published `http://127.0.0.1:9090` base address and
keep the query parameters.

## Reproduce the timeout manually

```bash
curl -i http://127.0.0.1:8081/api/v1/orders \
  -H 'Content-Type: application/json' \
  -d '{"productId":"book-1","quantity":2}'
```

The response should be HTTP 504 with code PAYMENT_TIMEOUT and an orderId. Health remains
UP because the application itself is running.

The simulation throws a controlled exception immediately. It does not reproduce an
actual network delay or explain why a real dependency would be slow.

## Container design

The following describes the base four-service Compose demo. The optional persistence
overlay adds PostgreSQL with its own writable data volume and a one-shot migration
service; see [persistence](persistence.md).

- Python dependencies are installed from uv.lock without development packages.
- The Python application is installed in non-editable mode.
- Java is built with Maven Wrapper and JDK 25, then runs in a JRE image.
- Python and Java run as a non-root user with UID 10001.
- The frontend serves its built assets from an unprivileged Nginx image.
- Java writes logs to the named demo-logs volume.
- Python mounts the same volume read-only.
- Prometheus runs as the image's non-root user and stores metrics in its own volume.
- Its configuration is mounted read-only; a missing source file stops startup.
- Root filesystems are read-only; /tmp is a temporary filesystem.
- Host ports are bound to 127.0.0.1.
- Prometheus starts after the Java health check succeeds.
- The investigator starts after both Java and Prometheus health checks succeed.
- The frontend starts after the investigator health check succeeds.
- LLM_ENABLED is explicitly false in default Compose.
- Default Compose does not pass OPENAI_API_KEY to the containers.
- Docker build contexts include only the files required for each image.

The Python and Java HTTP servers listen on 0.0.0.0 inside their containers. Frontend
Nginx listens on port 8080 and is published on host port 3000. This allows Docker's
published ports to reach the applications.

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

For a fresh capture of the base demo, remove both telemetry volumes:

```bash
docker compose down --volumes
```

The last command deletes captured logs and stored Prometheus metrics. Reading logs from
Python does not delete or consume them. Java continues appending to the active log file
and rotates it according to its Logback configuration. The investigator currently reads
only the active file.

For the persistence overlay, use the same two Compose files when stopping or removing
volumes. Removing its `investigation-data` volume also deletes saved investigations; see
[volume behavior](persistence.md#run-the-compose-demo-with-persistence).

## Troubleshooting

- Docker daemon unavailable: start Docker Desktop or Docker Engine.
- Port already allocated: stop an existing local service using port 3000, 8000, 8081, or 9090.
- Local frontend unavailable: check port 5173 and start `npm --prefix frontend run dev`.
- Frontend API request fails: confirm the investigator is healthy on port 8000;
  for Compose, inspect the frontend and investigator logs.
- Container unhealthy: inspect docker compose ps and docker compose logs.
- No matching evidence: check the source file, service, environment, and time window.
- Expected HTTP 504 but received 201: ensure the payment-timeout demo is running.
- Analysis failed: check API access, input limits, and model availability.
- OPENAI_API_KEY is required: load the local .env or disable analysis.
- Java compilation errors, including `ExceptionInInitializerError` / `EndPosTable`:
  run `mvnw -version` and select JDK 25 using the [local development commands](development.md#local-development).
- Prometheus target down: inspect its Targets page and Java container logs;
  the scrape address inside Docker is `order-service:8081`.
- Metrics check timed out: confirm the target is healthy and that the service
  remains running while the check waits for fresh scrapes.
- Prometheus bind mount missing: ensure
  `observability/prometheus/prometheus.yaml` exists in the checkout.
- Metrics source not connected: set `PROMETHEUS_URL` in the investigator process
  environment or load it through `uv run --env-file .env`.
- Metric query failed: check that the investigator can reach its configured
  Prometheus address and that the server supports the query parameters.
- No metric samples: check labels, time window, retention, and scrape health;
  a missing HTTP 504 series can mean it has not been created yet.
- Metric coverage incomplete: inspect the requested window and available scrapes.
- Metric collection skipped: use a window of at most one hour with at least one
  millisecond evaluation point.
- Actuator configuration invalid: set `ACTUATOR_URL`, `ACTUATOR_SERVICE`, and
  `ACTUATOR_ENVIRONMENT` together, or clear all three to disable the source.
- Actuator collection skipped: ensure the requested service/environment matches
  the configured target.
- Actuator identity could not be verified: check endpoint availability and the
  `app.name`, `app.environment`, and `app.version` fields in `/actuator/info`.
- Actuator identity mismatch: ensure the endpoint belongs to the requested
  service and environment; mismatched context is rejected.
- Actuator health unavailable: check the configured endpoint from the investigator's
  network and inspect the Java service logs.
- Current snapshot limitation in `missing_data`: this is intentional. Actuator
  reports current state, including when the requested incident window is historical.

- Configured database prevents startup: confirm PostgreSQL connectivity and run `uv run --locked alembic upgrade head` with the same `DATABASE_URL`.
- Saved-investigation reads return 503: enable storage with `DATABASE_URL` and check database availability. The nonpersistent POST still works when storage is disabled.
