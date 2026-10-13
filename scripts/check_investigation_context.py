import argparse
from datetime import UTC, datetime, timedelta

import httpx

from ai_incident_investigator.investigations.reports import (
    EvidenceSource,
    InvestigationReport,
)
from ai_incident_investigator.investigations.schemas import InvestigationRequest

EXPECTED_ACTUATOR_IDS = {"actuator-info", "actuator-health"}


def check_demo(*, investigator_url: str) -> None:
    now = datetime.now(UTC)

    request = InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=now - timedelta(minutes=5),
        end_time=now - timedelta(seconds=1),
        description=("Compare a historical incident window with current Actuator context."),
    )

    with httpx.Client(timeout=15.0, trust_env=False) as client:
        retrieval_started = datetime.now(UTC)

        response = client.post(
            f"{investigator_url.rstrip('/')}/investigations",
            json=request.model_dump(mode="json"),
        )
        response.raise_for_status()

        report = InvestigationReport.model_validate(response.json())
        retrieval_finished = datetime.now(UTC)

    if report.analysis_status != "not_requested":
        raise RuntimeError("This demo requires LLM analysis to be disabled")

    context = {
        item.id: item
        for item in report.evidence
        if item.source == EvidenceSource.ACTUATOR and item.service == request.service
    }

    if not EXPECTED_ACTUATOR_IDS <= context.keys():
        raise RuntimeError(f"Report did not contain Actuator health and info: {set(context)}")

    for evidence_id in EXPECTED_ACTUATOR_IDS:
        item = context[evidence_id]

        if not retrieval_started <= item.start_time <= retrieval_finished:
            raise RuntimeError(f"{evidence_id} did not use its actual retrieval time")

        if item.end_time is not None:
            raise RuntimeError(f"{evidence_id} must describe a snapshot, not a time range")

        if item.start_time <= request.end_time:
            raise RuntimeError(f"{evidence_id} was incorrectly backdated to the incident window")

    if "status=UP" not in context["actuator-health"].summary:
        raise RuntimeError("Actuator health evidence did not report the current UP status")

    info_summary = context["actuator-info"].summary

    if not all(
        value in info_summary
        for value in (
            "name=order-service",
            "environment=local",
            "version=0.1.0",
        )
    ):
        raise RuntimeError("Actuator info evidence did not contain the expected service identity")

    print(
        "Investigation context demo passed: "
        f"actuator_evidence={len(context)}; "
        f"analysis_status={report.analysis_status}."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=("Check current Actuator snapshots in an investigation report.")
    )
    parser.add_argument(
        "--investigator-url",
        default="http://127.0.0.1:8000",
    )

    args = parser.parse_args()

    try:
        check_demo(investigator_url=args.investigator_url)
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Investigation context demo failed: {exc}") from None


if __name__ == "__main__":
    main()
