# HTTP telemetry sources

The server configures telemetry targets; investigation payloads cannot supply arbitrary
source URLs or PromQL. For reproducible checks, see [demo
operations](demo-operations.md).

## Prometheus configuration

`PROMETHEUS_URL` is optional. An unset or empty value disables metric collection;
reports then include a data gap stating that the source is not connected.

| Run mode | Base URL |
| --- | --- |
| Investigator in Compose | `http://prometheus:9090` |
| Local investigator using the published Prometheus port | `http://127.0.0.1:9090` |

For a local investigator, set the address in the process environment or in a private
`.env` file loaded with `uv run --env-file .env`. The configured Prometheus must contain
telemetry for the same service, environment, and time window as the logs. Connecting a
server does not guarantee matching data.

Configuration accepts an HTTP or HTTPS base URL of at most 512 characters, without
embedded credentials, query parameters, or fragments. Authentication configuration is
not implemented. A client is opened for each investigation and closed afterwards; the
three metric queries share that client.

## Spring Boot Actuator context

The investigator can collect current application context from `/actuator/info` and
`/actuator/health`.

Configure all three variables together:

- `ACTUATOR_URL`: base URL of the Actuator endpoints, including `/actuator/`.
- `ACTUATOR_SERVICE`: service assigned to this endpoint.
- `ACTUATOR_ENVIRONMENT`: environment assigned to this endpoint.

All three unset or empty values disable Actuator collection. A partially configured
target is invalid and prevents startup. The base URL accepts HTTP or HTTPS, at most 512
characters, without embedded credentials, query parameters, or fragments. Authentication
configuration is not implemented.

| Run mode | Actuator base URL |
| --- | --- |
| Investigator in Compose | `http://order-service:8081/actuator/` |
| Local investigator using the published Java port | `http://127.0.0.1:8081/actuator/` |

The request's service and environment must match the configured target before any
Actuator request is sent. The collector then requires `/info` to provide `app.name`,
`app.environment`, and `app.version`, and checks the declared name/environment before
collecting health. The demo publishes these fields through `info.app.*` and
`management.info.env.enabled=true`; Maven replaces `@project.version@` with the POM
version during the build.

Only application name, environment, version, and overall health status are included in
the report. Additional info fields and health component details are ignored. HTTP 503
with health `DOWN` or `OUT_OF_SERVICE` is retained as an observation rather than treated
as a collection failure.

| Evidence ID | Observation |
| --- | --- |
| `actuator-info` | Current application name, environment, and version. |
| `actuator-health` | Current overall health status and response HTTP status. |

Actuator observations are current snapshots with their actual retrieval timestamps and
`end_time=None`. They do not establish the application's state during a historical
incident window. This limitation is reported in `missing_data`; an additional note
identifies snapshots outside the requested window. Each reference is the requested
endpoint URL, not a persisted copy of the response. Repeating the URL retrieves a new
snapshot.

If Actuator is unavailable or its identity cannot be verified, collected logs and
Prometheus evidence are retained.

The demo can report health `UP` while order requests return a simulated HTTP 504.
Overall application health does not prove that every business operation succeeds.

Run the Actuator integration check with:

```bash
uv run --locked python scripts/check_investigation_context.py
```

The check requires `actuator-info` and `actuator-health` evidence, the demo's
name/environment/version, current health `UP`, and `analysis_status=not_requested`. It
deliberately requests a historical window that ends before the HTTP call, then verifies
that snapshot timestamps fall inside the actual retrieval interval and have no end time.
This detects snapshots incorrectly dated as historical evidence.

An example successful result:

```text
Investigation context demo passed: actuator_evidence=2; analysis_status=not_requested.
```
