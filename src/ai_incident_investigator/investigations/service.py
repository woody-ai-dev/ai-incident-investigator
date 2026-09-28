from ai_incident_investigator.investigations.reports import InvestigationReport, RecommendedCheck
from ai_incident_investigator.investigations.schemas import InvestigationRequest


def investigate(request: InvestigationRequest) -> InvestigationReport:
    """Return an inconclusive report until telemetry sources are connected."""
    return InvestigationReport(
        summary=(
            f"Cannot determine the cause of the incident for service '{request.service}' "
            f"in environment '{request.environment}' between "
            f"{request.start_time.isoformat()} and {request.end_time.isoformat()}: "
            "telemetry sources are not connected."
        ),
        evidence=[],
        findings=[],
        hypotheses=[],
        recommended_checks=[
            RecommendedCheck(
                action="Collect service logs for the requested time window.",
                reason="Logs are needed to identify recorded errors and affected operations.",
            ),
        ],
        missing_data=[
            "Service logs are unavailable: the log source is not connected.",
            "Prometheus metrics are unavailable: the metrics source is not connected.",
            "Distributed traces are unavailable: the trace source is not connected.",
            "Actuator context is unavailable: the Actuator source is not connected.",
        ],
    )
