import argparse
from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, Field

from ai_incident_investigator.investigations.reports import EvidenceSource, InvestigationReport
from ai_incident_investigator.investigations.schemas import InvestigationRequest

EXPECTED_METRIC_IDS = {"metric-up", "metric-jvm-heap", "metric-http-504-counter"}


class TimeoutProblem(BaseModel):
    code: Literal["PAYMENT_TIMEOUT"]
    order_id: UUID = Field(alias="orderId")


def check_demo(*, orders_url: str, investigator_url: str) -> None:
    orders_url = orders_url.rstrip("/")
    investigator_url = investigator_url.rstrip("/")
    start_time = datetime.now(UTC) - timedelta(seconds=30)

    with httpx.Client(timeout=15.0, trust_env=False) as client:
        order_response = client.post(
            f"{orders_url}/api/v1/orders",
            json={"productId": "book-1", "quantity": 2},
        )
        if order_response.status_code != 504:
            raise RuntimeError(f"Expected HTTP 504, got {order_response.status_code}")

        problem = TimeoutProblem.model_validate(order_response.json())
        deadline = monotonic() + 30.0
        metric_ids: set[str] = set()

        while monotonic() < deadline:
            request = InvestigationRequest(
                service="order-service",
                environment="local",
                start_time=start_time,
                end_time=datetime.now(UTC),
                description=f"Investigate simulated payment timeout for order {problem.order_id}.",
            )
            response = client.post(
                f"{investigator_url}/investigations",
                json=request.model_dump(mode="json"),
            )
            response.raise_for_status()
            report = InvestigationReport.model_validate(response.json())

            if report.analysis_status != "not_requested":
                raise RuntimeError("This demo requires LLM analysis to be disabled")

            timeout_found = any(
                item.source == EvidenceSource.LOG
                and item.service == request.service
                and item.summary.startswith("[ERROR]")
                and "Payment request timed out (simulated)" in item.summary
                and f"order={problem.order_id}" in item.summary
                for item in report.evidence
            )
            metric_ids = {
                item.id
                for item in report.evidence
                if item.source == EvidenceSource.METRIC and item.service == request.service
            }

            if timeout_found and EXPECTED_METRIC_IDS <= metric_ids:
                print(
                    f"Investigation metrics demo passed: order={problem.order_id}; "
                    f"metric_evidence={len(metric_ids)}; analysis_status={report.analysis_status}."
                )
                return

            sleep(min(1.0, max(0.0, deadline - monotonic())))

    raise RuntimeError(f"Report did not contain timeout logs and all metric IDs: {metric_ids}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check logs and metrics in an investigation report."
    )
    parser.add_argument("--orders-url", default="http://127.0.0.1:8081")
    parser.add_argument("--investigator-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    try:
        check_demo(orders_url=args.orders_url, investigator_url=args.investigator_url)
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Investigation metrics demo failed: {exc}") from None


if __name__ == "__main__":
    main()
