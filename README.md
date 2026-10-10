## Prometheus demo

The Java service exposes HTTP and JVM metrics through
`/actuator/prometheus`. Prometheus scrapes the service every five seconds
and stores its data in the `prometheus-data` volume.

| Component | Address |
| --- | --- |
| Java metrics exporter | http://127.0.0.1:8081/actuator/prometheus |
| Prometheus interface | http://127.0.0.1:9090 |

Validate the running Prometheus configuration:

```bash
docker compose exec -T prometheus \
  /bin/promtool check config /etc/prometheus/prometheus.yml
```

Check metrics collection:

```bash
uv run --locked python scripts/check_prometheus_demo.py
```

The check waits for a fresh scrape, verifies target availability and JVM
heap metrics, creates an order that returns HTTP 504, and waits for the
HTTP 504 counter to increase.

The counter represents aggregated requests. Order IDs remain in logs
and are not added as metric labels.

Prometheus metrics are available in this demo, but the investigator does
not yet include them in investigation reports. LLM analysis remains
disabled in Compose.