import logging
from pathlib import Path

from pydantic import ValidationError

from ai_incident_investigator.investigations.analysis import AnalysisError, Analyzer
from ai_incident_investigator.investigations.reports import InvestigationReport, RecommendedCheck
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.sources.logs import collect_logs

logger = logging.getLogger(__name__)


def investigate(
    request: InvestigationRequest,
    *,
    log_path: Path,
    analyzer: Analyzer | None = None,
) -> InvestigationReport:
    logs = collect_logs(log_path, request)

    report = InvestigationReport(
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
                action="Review collected logs and reported data gaps.",
                reason="Available log events may not explain the root cause.",
            ),
        ],
        missing_data=[
            *logs.issues,
            "Prometheus metrics are unavailable: the metrics source is not connected.",
            "Distributed traces are unavailable: the trace source is not connected.",
            "Actuator context is unavailable: the Actuator source is not connected.",
        ],
    )

    if analyzer is None:
        return report

    if not report.evidence:
        report.analysis_status = "skipped"
        return report

    try:
        analysis = analyzer.analyze(request, report.evidence, report.missing_data)

        return InvestigationReport.model_validate(
            report.model_dump() | analysis.model_dump() | {"analysis_status": "completed"}
        )
    except (AnalysisError, ValidationError) as exc:
        logger.warning(
            "Investigation analysis failed: %s",
            type(exc.__cause__ or exc).__name__,
        )

        report.analysis_status = "failed"
        report.missing_data.append(
            "LLM analysis failed or was rejected; collected evidence has been retained."
        )

        return report
