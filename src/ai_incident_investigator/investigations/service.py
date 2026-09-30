from pathlib import Path

from ai_incident_investigator.investigations.reports import InvestigationReport, RecommendedCheck
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.sources.logs import collect_logs


def investigate(request: InvestigationRequest, *, log_path: Path) -> InvestigationReport:
    logs = collect_logs(log_path, request)

    return InvestigationReport(
        summary=(
            f"Collected {len(logs.evidence)} log record(s) for service '{request.service}' "
            f"in environment '{request.environment}' between "
            f"{request.start_time.isoformat()} and {request.end_time.isoformat()} "
            "(end excluded). The incident cause has not been determined."
        ),
        evidence=logs.evidence,
        findings=[],
        hypotheses=[],
        recommended_checks=[
            RecommendedCheck(
                action="Collect service logs for the requested time window.",
                reason="Logs are needed to identify recorded errors and affected operations.",
            ),
        ],
        missing_data=[
            *logs.issues,
            "Prometheus metrics are unavailable: the metrics source is not connected.",
            "Distributed traces are unavailable: the trace source is not connected.",
            "Actuator context is unavailable: the Actuator source is not connected.",
        ],
    )
