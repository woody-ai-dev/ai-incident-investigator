import argparse
import math
from collections.abc import Callable
from time import monotonic, sleep, time
from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, FiniteFloat

TARGET_LABELS = 'job="order-service",service="order-service",environment="local"'

UP_QUERY = f"min(up{{{TARGET_LABELS}}})"

SCRAPE_TIME_QUERY = f"min(timestamp(up{{{TARGET_LABELS}}}))"

HEAP_QUERY = f'sum(jvm_memory_used_bytes{{{TARGET_LABELS},area="heap"}})'

TIMEOUT_QUERY = (
    f"sum(http_server_requests_seconds_count{{{TARGET_LABELS},"
    'uri="/api/v1/orders",method="POST",status="504"})'
)


class QuerySample(BaseModel):
    value: tuple[FiniteFloat, str]


class QueryData(BaseModel):
    result_type: Literal["vector"] = Field(alias="resultType")
    result: list[QuerySample] = Field(max_length=1)


class QueryResponse(BaseModel):
    status: Literal["success"]
    data: QueryData
    warnings: list[str] = Field(default_factory=list)


class TimeoutProblem(BaseModel):
    code: Literal["PAYMENT_TIMEOUT"]
    order_id: UUID = Field(alias="orderId")


def read_value(
    client: httpx.Client,
    *,
    prometheus_url: str,
    query: str,
    timeout: float = 5.0,
) -> float | None:
    response = client.get(
        f"{prometheus_url}/api/v1/query",
        params={"query": query, "timeout": "2s"},
        timeout=timeout,
    )
    response.raise_for_status()

    body = QueryResponse.model_validate(response.json())

    if body.warnings:
        raise RuntimeError(f"Prometheus returned query warnings: {body.warnings}")

    if not body.data.result:
        return None

    value = float(body.data.result[0].value[1])

    if not math.isfinite(value) or value < 0:
        raise ValueError("Expected a finite, non-negative metric value")

    return value


def wait_for_value(
    client: httpx.Client,
    *,
    prometheus_url: str,
    query: str,
    condition: Callable[[float], bool],
    description: str,
    wait_seconds: float = 30.0,
) -> float:
    deadline = monotonic() + wait_seconds
    last_value: float | None = None

    while (remaining := deadline - monotonic()) > 0:
        last_value = read_value(
            client,
            prometheus_url=prometheus_url,
            query=query,
            timeout=min(5.0, remaining),
        )

        if last_value is not None and condition(last_value):
            return last_value

        sleep(
            min(
                1.0,
                max(0.0, deadline - monotonic()),
            )
        )

    raise RuntimeError(f"Timed out waiting for {description}; last value={last_value}")


def check_demo(
    client: httpx.Client,
    *,
    orders_url: str,
    prometheus_url: str,
) -> None:
    orders_url = orders_url.rstrip("/")
    prometheus_url = prometheus_url.rstrip("/")

    exporter_response = client.get(f"{orders_url}/actuator/prometheus")
    exporter_response.raise_for_status()

    started_at = time()

    wait_for_value(
        client,
        prometheus_url=prometheus_url,
        query=SCRAPE_TIME_QUERY,
        condition=lambda value: value >= started_at,
        description="a fresh order-service scrape",
    )

    up = read_value(
        client,
        prometheus_url=prometheus_url,
        query=UP_QUERY,
    )

    if up != 1.0:
        raise RuntimeError(f"Prometheus cannot scrape order-service: up={up}")

    heap_bytes = read_value(
        client,
        prometheus_url=prometheus_url,
        query=HEAP_QUERY,
    )

    if heap_bytes is None:
        raise RuntimeError("Prometheus did not contain JVM heap metrics")

    before = read_value(
        client,
        prometheus_url=prometheus_url,
        query=TIMEOUT_QUERY,
    )

    # The HTTP 504 series may not exist before the demo's first timeout.
    baseline = 0.0 if before is None else before

    order_response = client.post(
        f"{orders_url}/api/v1/orders",
        json={"productId": "book-1", "quantity": 2},
    )

    if order_response.status_code != 504:
        raise RuntimeError(f"Expected simulated HTTP 504, got {order_response.status_code}")

    problem = TimeoutProblem.model_validate(order_response.json())

    after = wait_for_value(
        client,
        prometheus_url=prometheus_url,
        query=TIMEOUT_QUERY,
        condition=lambda value: value >= baseline + 1.0,
        description="the HTTP 504 counter to increase",
    )

    print(
        f"Prometheus demo passed: order={problem.order_id}; "
        f"http_504_count={baseline:g}->{after:g}; "
        f"heap_bytes={heap_bytes:g}."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Prometheus metrics for the Compose demo.")
    parser.add_argument(
        "--orders-url",
        default="http://127.0.0.1:8081",
    )
    parser.add_argument(
        "--prometheus-url",
        default="http://127.0.0.1:9090",
    )
    args = parser.parse_args()

    try:
        with httpx.Client(timeout=5.0, trust_env=False) as client:
            check_demo(
                client,
                orders_url=args.orders_url,
                prometheus_url=args.prometheus_url,
            )
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Prometheus demo failed: {exc}") from None


if __name__ == "__main__":
    main()
