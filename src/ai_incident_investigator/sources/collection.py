from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter_ns

from pydantic import BaseModel, Field

from ai_incident_investigator.investigations.reports import (
    CollectionStatus,
    Evidence,
    EvidenceSource,
    SourceCollection,
)


class CollectionResult(BaseModel):
    # Older recorded fixtures may not contain an explicit collection outcome.
    status: CollectionStatus | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class CollectedSource:
    result: CollectionResult
    metadata: SourceCollection


def collect_source(
    source: EvidenceSource,
    operation: Callable[[], CollectionResult] | None,
    *,
    disabled_reason: str,
) -> CollectedSource:
    if operation is None:
        result = CollectionResult(status=CollectionStatus.DISABLED, issues=[disabled_reason])
        duration_ms = None
    else:
        started = perf_counter_ns()
        result = operation()
        duration_ms = (perf_counter_ns() - started) // 1_000_000

    return CollectedSource(
        result=result,
        metadata=SourceCollection(
            source=source,
            status=(result.status if result.status is not None else CollectionStatus.NOT_RECORDED),
            evidence_count=len(result.evidence),
            duration_ms=duration_ms,
            issues=list(result.issues),
        ),
    )
