"""Producer-owned meanings and limits of the supported metric evidence."""

from dataclasses import dataclass
from enum import StrEnum


class MetricKind(StrEnum):
    SCRAPE_SUCCESS = "scrape_success"
    JVM_HEAP_USAGE = "jvm_heap_usage"
    CUMULATIVE_HTTP_COUNTER = "cumulative_http_counter"


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    description: str
    kind: MetricKind
    supported_observation: str
    limitations: tuple[str, ...]

    @property
    def evidence_id(self) -> str:
        return f"metric-{self.key}"


SCRAPE_SUCCESS = MetricDefinition(
    key="up",
    description="Minimum scrape availability across observed targets (0 or 1)",
    kind=MetricKind.SCRAPE_SUCCESS,
    supported_observation=(
        "At evaluated observations, min(up)=1 records successful metrics scraping for the "
        "observed targets, while min(up)=0 records at least one failed scrape."
    ),
    limitations=(
        "Scrape success is not an HTTP health endpoint check and does not establish business "
        "availability.",
        "Only evaluated observations are represented; they do not establish continuity, "
        "continuous availability, recovery, an incident end time, or behavior between "
        "observations.",
        "Evaluation times can reuse samples within the lookback period and are not scrape times.",
        "A failed metrics scrape (up=0) does not establish business downtime.",
    ),
)

JVM_HEAP_USAGE = MetricDefinition(
    key="jvm-heap",
    description="Aggregated JVM heap usage in bytes",
    kind=MetricKind.JVM_HEAP_USAGE,
    supported_observation=(
        "Minimum, maximum, and last evaluated aggregate JVM heap usage in bytes across "
        "observed targets."
    ),
    limitations=(
        "Aggregate min/max/last values alone do not establish heap pressure, stability, a memory "
        "leak, or out-of-memory (OOM) behavior; heap limits, garbage-collection data, and a "
        "baseline are needed to assess those claims.",
        "Aggregate values can hide per-target changes and do not identify a particular instance.",
    ),
)

HTTP_504_COUNTER = MetricDefinition(
    key="http-504-counter",
    description=(
        "Aggregated cumulative HTTP 504 counter for POST /api/v1/orders; "
        "may reset; not the number of errors in the investigation window"
    ),
    kind=MetricKind.CUMULATIVE_HTTP_COUNTER,
    supported_observation=(
        "Minimum, maximum, and last evaluated aggregate cumulative HTTP 504 counter for "
        "POST /api/v1/orders."
    ),
    limitations=(
        "Cumulative counter values are not the number of errors in the investigation window; "
        "aggregate differences alone do not establish a window count or error rate.",
        "Counter resets, restarts, and target changes are unconfirmed; raw per-target series "
        "are needed to assess them.",
        "Aggregate min/max/last values alone do not establish an error burst, recovery, or "
        "incident duration.",
    ),
)

METRIC_DEFINITIONS = (SCRAPE_SUCCESS, JVM_HEAP_USAGE, HTTP_504_COUNTER)

_DEFINITIONS_BY_EVIDENCE_ID = {
    definition.evidence_id: definition for definition in METRIC_DEFINITIONS
}


def metric_definition(evidence_id: str) -> MetricDefinition | None:
    """Resolve only evidence IDs emitted by a registered metric producer."""
    return _DEFINITIONS_BY_EVIDENCE_ID.get(evidence_id)
