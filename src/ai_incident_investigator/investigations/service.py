import logging
from pathlib import Path

from pydantic import ValidationError

from ai_incident_investigator.investigations.analysis import AnalysisError, Analyzer
from ai_incident_investigator.investigations.evidence_context import (
    validate_hypothesis_time_support,
)
from ai_incident_investigator.investigations.reports import (
    InvestigationReport,
    RecommendedCheck,
)
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.sources.context import (
    ActuatorCollection,
    ActuatorCollector,
)
from ai_incident_investigator.sources.logs import collect_logs
from ai_incident_investigator.sources.metrics import (
    MetricsCollection,
    MetricsCollector,
)

logger = logging.getLogger(__name__)


def investigate(
    request: InvestigationRequest,
    *,
    log_path: Path,
    metrics_collector: MetricsCollector | None = None,
    actuator_collector: ActuatorCollector | None = None,
    analyzer: Analyzer | None = None,
) -> InvestigationReport:
    logs = collect_logs(log_path, request)

    metrics = (
        metrics_collector.collect(request)
        if metrics_collector is not None
        else MetricsCollection(
            issues=["Prometheus metrics are unavailable: the metrics source is not connected."]
        )
    )

    context = (
        actuator_collector.collect(request)
        if actuator_collector is not None
        else ActuatorCollection(
            issues=["Actuator context is unavailable: the Actuator source is not connected."]
        )
    )

    report = InvestigationReport(
        summary=(
            f"Investigated service '{request.service}' "
            f"in environment '{request.environment}'. "
            f"Collected {len(logs.evidence)} log record(s) and "
            f"{len(metrics.evidence)} metric observation(s) "
            "for the incident window between "
            f"{request.start_time.isoformat()} and "
            f"{request.end_time.isoformat()} "
            f"(end excluded), plus {len(context.evidence)} "
            "current Actuator snapshot(s). "
            "The incident cause has not been determined."
        ),
        evidence=[
            *logs.evidence,
            *metrics.evidence,
            *context.evidence,
        ],
        findings=[],
        hypotheses=[],
        recommended_checks=[
            RecommendedCheck(
                action="Review collected evidence and reported data gaps.",
                reason="Available observations may not explain the root cause.",
            ),
        ],
        missing_data=[
            *logs.issues,
            *metrics.issues,
            *context.issues,
            "Distributed traces are unavailable: the trace source is not connected.",
        ],
    )

    if analyzer is None:
        return report

    if not report.evidence:
        report.analysis_status = "skipped"
        return report

    try:
        analysis = analyzer.analyze(
            request,
            report.evidence,
            report.missing_data,
        )

        candidate = InvestigationReport.model_validate(
            report.model_dump() | analysis.model_dump() | {"analysis_status": "completed"}
        )
        validate_hypothesis_time_support(request, candidate)
        return candidate
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
