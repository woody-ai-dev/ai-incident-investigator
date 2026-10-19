from collections.abc import Sequence
from enum import StrEnum

from ai_incident_investigator.investigations.analysis import AnalysisError
from ai_incident_investigator.investigations.metric_catalog import MetricKind, metric_definition
from ai_incident_investigator.investigations.reports import (
    Evidence,
    EvidenceSource,
    Identifier,
    InvestigationReport,
    ReportModel,
    ReportText,
)
from ai_incident_investigator.investigations.schemas import InvestigationRequest


class ObservationKind(StrEnum):
    POINT = "point_observation"
    INTERVAL = "interval_observation"


class EvidenceTimeScope(StrEnum):
    BEFORE_WINDOW = "before_window"
    WITHIN_WINDOW = "within_window"
    OVERLAPS_WINDOW = "overlaps_window"
    AFTER_WINDOW = "after_window"


class MetricInterpretation(ReportModel):
    kind: MetricKind
    supported_observation: ReportText
    limitations: tuple[ReportText, ...]


class EvidenceContext(ReportModel):
    """Input-only metadata; not part of the public evidence contract."""

    evidence_id: Identifier
    observation_kind: ObservationKind
    time_scope: EvidenceTimeScope
    metric_interpretation: MetricInterpretation | None = None


def evidence_time_scope(
    request: InvestigationRequest,
    item: Evidence,
) -> EvidenceTimeScope:
    """Compare an observation with the half-open incident window [start, end)."""
    if item.end_time is None:
        if item.start_time < request.start_time:
            return EvidenceTimeScope.BEFORE_WINDOW
        if item.start_time >= request.end_time:
            return EvidenceTimeScope.AFTER_WINDOW
        return EvidenceTimeScope.WITHIN_WINDOW

    if item.end_time <= request.start_time:
        return EvidenceTimeScope.BEFORE_WINDOW
    if item.start_time >= request.end_time:
        return EvidenceTimeScope.AFTER_WINDOW
    if item.start_time >= request.start_time and item.end_time <= request.end_time:
        return EvidenceTimeScope.WITHIN_WINDOW
    return EvidenceTimeScope.OVERLAPS_WINDOW


def build_evidence_context(
    request: InvestigationRequest,
    evidence: Sequence[Evidence],
) -> list[EvidenceContext]:
    return [
        EvidenceContext(
            evidence_id=item.id,
            observation_kind=(
                ObservationKind.POINT if item.end_time is None else ObservationKind.INTERVAL
            ),
            time_scope=evidence_time_scope(request, item),
            metric_interpretation=_metric_interpretation(item),
        )
        for item in evidence
    ]


def _metric_interpretation(item: Evidence) -> MetricInterpretation | None:
    if item.source != EvidenceSource.METRIC:
        return None

    definition = metric_definition(item.id)
    if definition is None:
        return None

    return MetricInterpretation(
        kind=definition.kind,
        supported_observation=definition.supported_observation,
        limitations=definition.limitations,
    )


def validate_hypothesis_time_support(
    request: InvestigationRequest,
    report: InvestigationReport,
) -> None:
    """Reject hypotheses supported only by out-of-window Actuator point snapshots.

    Run after report reference validation. This rule does not assess claim meaning
    or establish that other combinations of supporting evidence are sufficient.
    """
    by_id = {item.id: item for item in report.evidence}

    for hypothesis in report.hypotheses:
        supporting = [by_id[identifier] for identifier in hypothesis.supporting_evidence_ids]

        if all(
            item.source == EvidenceSource.ACTUATOR
            and item.end_time is None
            and evidence_time_scope(request, item)
            in {EvidenceTimeScope.BEFORE_WINDOW, EvidenceTimeScope.AFTER_WINDOW}
            for item in supporting
        ):
            raise AnalysisError(
                "A hypothesis is supported only by Actuator snapshots outside the incident window"
            )
