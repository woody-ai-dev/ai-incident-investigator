import argparse
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx

from ai_incident_investigator.investigations.records import StoredInvestigation
from ai_incident_investigator.investigations.reports import InvestigationReport
from ai_incident_investigator.investigations.schemas import InvestigationRequest


def check_storage(*, investigator_url: str) -> UUID:
    url = investigator_url.rstrip("/")
    end_time = datetime.now(UTC)
    request = InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=end_time - timedelta(minutes=15),
        end_time=end_time,
        description="Verify persistence with LLM analysis disabled.",
    )
    with httpx.Client(timeout=30.0, trust_env=False) as client:
        response = client.post(f"{url}/investigations", json=request.model_dump(mode="json"))
        response.raise_for_status()
        report = InvestigationReport.model_validate(response.json())
        if report.analysis_status != "not_requested":
            raise RuntimeError("Run this check against a demo with LLM_ENABLED=false")
        raw_id = response.headers.get("X-Investigation-ID")
        if raw_id is None:
            raise RuntimeError("The response did not contain a saved investigation ID")
        investigation_id = UUID(raw_id)
        saved_response = client.get(f"{url}/investigations/{investigation_id}")
        saved_response.raise_for_status()
        saved = StoredInvestigation.model_validate(saved_response.json())
        if saved.id != investigation_id or saved.request != request or saved.report != report:
            raise RuntimeError("The saved investigation does not match the original response")
    return investigation_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Check saved investigation retrieval.")
    parser.add_argument("--investigator-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        investigation_id = check_storage(investigator_url=args.investigator_url)
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Storage check failed: {exc}") from None
    print(f"Storage check passed: investigation={investigation_id}")


if __name__ == "__main__":
    main()
