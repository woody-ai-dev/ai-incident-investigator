from ai_incident_investigator.investigations.evidence_context import (
    EvidenceTimeScope,
    evidence_time_scope,
)
from ai_incident_investigator.investigations.reports import CollectionStatus, EvidenceSource
from ai_incident_investigator.knowledge.models import LogPrefixRule, MetricRule
from ai_incident_investigator.knowledge.recommendations import InvestigationExport
from ai_incident_investigator.knowledge.vector_index import SearchHit

_LOG_LEVELS = {"[TRACE]", "[DEBUG]", "[INFO]", "[WARN]", "[ERROR]", "[FATAL]"}


def _log_message(summary: str) -> str:
    level, _, message = summary.partition(" ")
    return message if level in _LOG_LEVELS else summary


def applicable_hits(
    investigation: InvestigationExport, hits: tuple[SearchHit, ...]
) -> tuple[SearchHit, ...]:
    """Apply catalog rules to original observations while preserving search order."""
    request, report = investigation.request, investigation.report
    observations = [
        item
        for item in report.evidence
        if evidence_time_scope(request, item)
        in {EvidenceTimeScope.WITHIN_WINDOW, EvidenceTimeScope.OVERLAPS_WINDOW}
    ]
    log_messages = [
        _log_message(item.summary) for item in observations if item.source == EvidenceSource.LOG
    ]
    metric_ids = {item.id for item in observations if item.source == EvidenceSource.METRIC}
    collection_gap = any(
        item.status != CollectionStatus.COLLECTED for item in report.source_collections or ()
    )

    accepted = []
    for hit in hits:
        rules = hit.chunk.document.applicability
        if rules is None:
            accepted.append(hit)
            continue
        for rule in rules:
            if isinstance(rule, LogPrefixRule):
                matches = any(message.startswith(rule.prefix) for message in log_messages)
            elif isinstance(rule, MetricRule):
                matches = rule.evidence_id in metric_ids
            else:
                matches = collection_gap
            if matches:
                accepted.append(hit)
                break
    return tuple(accepted)
