import argparse
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx

from ai_incident_investigator.investigations.reports import EvidenceSource, InvestigationReport
from ai_incident_investigator.investigations.schemas import InvestigationRequest


def check_health(client: httpx.Client, url: str) -> None:
    response = client.get(url)
    response.raise_for_status()
    body = response.json()

    if not isinstance(body, dict) or body.get("status") != "UP":
        raise RuntimeError(f"Health check did not report UP: {url}")


def check_demo(*, orders_url: str, investigator_url: str) -> None:
    orders_url = orders_url.rstrip("/")
    investigator_url = investigator_url.rstrip("/")

    with httpx.Client(timeout=10.0, trust_env=False) as client:
        check_health(client, f"{orders_url}/actuator/health")
        check_health(client, f"{investigator_url}/health")

        start_time = datetime.now(UTC) - timedelta(seconds=5)

        order_response = client.post(
            f"{orders_url}/api/v1/orders",
            json={"productId": "book-1", "quantity": 2},
        )

        if order_response.status_code != 504:
            raise RuntimeError(f"Expected simulated HTTP 504, got {order_response.status_code}")

        problem = order_response.json()
        if not isinstance(problem, dict) or problem.get("code") != "PAYMENT_TIMEOUT":
            raise RuntimeError("Order response did not contain PAYMENT_TIMEOUT")

        raw_order_id = problem.get("orderId")
        if not isinstance(raw_order_id, str):
            raise RuntimeError("Order response did not contain a string orderId")

        order_id = UUID(raw_order_id)

        request = InvestigationRequest(
            service="order-service",
            environment="local",
            start_time=start_time,
            end_time=datetime.now(UTC) + timedelta(seconds=1),
            description=f"Order {order_id} failed with PAYMENT_TIMEOUT in the Compose demo.",
        )

        investigation_response = client.post(
            f"{investigator_url}/investigations",
            json=request.model_dump(mode="json"),
        )
        investigation_response.raise_for_status()

        report = InvestigationReport.model_validate(investigation_response.json())

    if report.analysis_status != "not_requested":
        raise RuntimeError("Compose demo must run with LLM analysis disabled")

    timeout_found = any(
        item.source == EvidenceSource.LOG
        and item.service == request.service
        and item.summary.startswith("[ERROR]")
        and "Payment request timed out (simulated)" in item.summary
        and f"order={order_id}" in item.summary
        and item.reference.startswith("local-jsonl:line:")
        for item in report.evidence
    )

    if not timeout_found:
        raise RuntimeError("Investigation did not contain timeout evidence for the created order")

    print(
        f"Compose demo passed: order={order_id}; "
        f"evidence={len(report.evidence)}; "
        f"analysis_status={report.analysis_status}."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the Compose payment-timeout demo.")
    parser.add_argument("--orders-url", default="http://127.0.0.1:8081")
    parser.add_argument("--investigator-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    try:
        check_demo(orders_url=args.orders_url, investigator_url=args.investigator_url)
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Compose demo failed: {exc}") from None


if __name__ == "__main__":
    main()
