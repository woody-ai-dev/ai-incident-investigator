from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import UUID

from ai_incident_investigator.investigations.analysis import Analyzer
from ai_incident_investigator.investigations.ports import InvestigationStore
from ai_incident_investigator.investigations.records import StoredInvestigation
from ai_incident_investigator.investigations.reports import InvestigationReport
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.investigations.service import investigate
from ai_incident_investigator.sources.context import ActuatorCollector
from ai_incident_investigator.sources.metrics import MetricsCollector


@dataclass(frozen=True)
class AnalysisConfiguration:
    """Configured analysis settings, not evidence that a provider was called."""

    configured_model: str | None = None
    prompt_sha256: str | None = None


@dataclass(frozen=True)
class InvestigationExecution:
    report: InvestigationReport
    investigation_id: UUID | None = None


def execute_investigation(
    request: InvestigationRequest,
    *,
    log_path: Path,
    metrics_collector: MetricsCollector | None = None,
    actuator_collector: ActuatorCollector | None = None,
    analyzer: Analyzer | None = None,
    store: InvestigationStore | None = None,
    analysis_configuration: AnalysisConfiguration | None = None,
) -> InvestigationExecution:
    """Run collection and analysis, then commit an optional completed snapshot.

    Timing excludes persistence. No database transaction is held while sources or
    the analyzer are running. Storage failures propagate to the caller; an ID is
    returned only after save() has committed successfully.
    """
    started = perf_counter()
    report = investigate(
        request,
        log_path=log_path,
        metrics_collector=metrics_collector,
        actuator_collector=actuator_collector,
        analyzer=analyzer,
    )
    duration_ms = round((perf_counter() - started) * 1000)
    if store is None:
        return InvestigationExecution(report=report)

    configuration = analysis_configuration or AnalysisConfiguration()
    record = StoredInvestigation(
        duration_ms=duration_ms,
        configured_model=configuration.configured_model,
        prompt_sha256=configuration.prompt_sha256,
        request=request,
        report=report,
    )
    store.save(record)
    return InvestigationExecution(report=report, investigation_id=record.id)
