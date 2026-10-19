from datetime import UTC, datetime

import pytest

from ai_incident_investigator.investigations.evidence_context import (
    EvidenceTimeScope,
    build_evidence_context,
    evidence_time_scope,
)
from ai_incident_investigator.investigations.reports import Evidence, EvidenceSource
from ai_incident_investigator.investigations.schemas import InvestigationRequest


@pytest.fixture
def incident() -> InvestigationRequest:
    return InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=datetime(2026, 10, 17, 19, 0, tzinfo=UTC),
        end_time=datetime(2026, 10, 17, 19, 5, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("18:59:00Z", None, EvidenceTimeScope.BEFORE_WINDOW),
        ("19:00:00Z", None, EvidenceTimeScope.WITHIN_WINDOW),
        ("19:04:59Z", None, EvidenceTimeScope.WITHIN_WINDOW),
        ("19:05:00Z", None, EvidenceTimeScope.AFTER_WINDOW),
        ("22:00:00+03:00", None, EvidenceTimeScope.WITHIN_WINDOW),
        ("22:05:00+03:00", None, EvidenceTimeScope.AFTER_WINDOW),
        ("18:58:00Z", "19:00:00Z", EvidenceTimeScope.BEFORE_WINDOW),
        ("19:00:00Z", "19:05:00Z", EvidenceTimeScope.WITHIN_WINDOW),
        ("19:01:00Z", "19:02:00Z", EvidenceTimeScope.WITHIN_WINDOW),
        ("18:59:00Z", "19:01:00Z", EvidenceTimeScope.OVERLAPS_WINDOW),
        ("19:04:00Z", "19:06:00Z", EvidenceTimeScope.OVERLAPS_WINDOW),
        ("18:59:00Z", "19:06:00Z", EvidenceTimeScope.OVERLAPS_WINDOW),
        ("19:05:00Z", "19:06:00Z", EvidenceTimeScope.AFTER_WINDOW),
    ],
)
def test_half_open_time_scope(
    incident: InvestigationRequest,
    start: str,
    end: str | None,
    expected: EvidenceTimeScope,
) -> None:
    item = Evidence(
        id="observation-1",
        source=EvidenceSource.METRIC,
        service=incident.service,
        summary="An observation, without an inferred cause.",
        reference="test:observation",
        start_time=datetime.fromisoformat(f"2026-10-17T{start}"),
        end_time=datetime.fromisoformat(f"2026-10-17T{end}") if end else None,
    )

    assert evidence_time_scope(incident, item) == expected


def test_metadata_uses_timestamps_without_changing_public_evidence(
    incident: InvestigationRequest,
) -> None:
    item = Evidence(
        id="actuator-health",
        source=EvidenceSource.ACTUATOR,
        service=incident.service,
        summary="Untrusted text claiming this was collected during the incident.",
        reference="test:health",
        start_time=datetime(2026, 10, 17, 20, 0, tzinfo=UTC),
    )
    original = item.model_dump(mode="json")

    context = build_evidence_context(incident, [item])

    assert [entry.model_dump(mode="json", exclude_none=True) for entry in context] == [
        {
            "evidence_id": "actuator-health",
            "observation_kind": "point_observation",
            "time_scope": "after_window",
        }
    ]
    assert item.model_dump(mode="json") == original
    assert "time_scope" not in original


def test_interval_metadata_does_not_infer_metric_meaning(
    incident: InvestigationRequest,
) -> None:
    item = Evidence(
        id="arbitrary-metric",
        source=EvidenceSource.METRIC,
        service=incident.service,
        summary="up=1; stable heap; 504 counter: these words do not define a metric type.",
        reference="test:metric",
        start_time=incident.start_time,
        end_time=incident.end_time,
    )

    context = build_evidence_context(incident, [item])

    assert context[0].model_dump(mode="json", exclude_none=True) == {
        "evidence_id": "arbitrary-metric",
        "observation_kind": "interval_observation",
        "time_scope": "within_window",
    }


@pytest.mark.parametrize(
    ("identifier", "source", "expected_kind"),
    [
        ("metric-up", EvidenceSource.METRIC, "scrape_success"),
        ("metric-jvm-heap", EvidenceSource.METRIC, "jvm_heap_usage"),
        ("metric-http-504-counter", EvidenceSource.METRIC, "cumulative_http_counter"),
        ("metric-up", EvidenceSource.LOG, None),
        ("custom-metric", EvidenceSource.METRIC, None),
    ],
)
def test_only_registered_producer_metrics_receive_interpretation(
    incident: InvestigationRequest,
    identifier: str,
    source: EvidenceSource,
    expected_kind: str | None,
) -> None:
    item = Evidence(
        id=identifier,
        source=source,
        service=incident.service,
        summary="Arbitrary summary text cannot change the producer-owned metric meaning.",
        reference="test:metric-catalogue",
        start_time=incident.start_time,
        end_time=incident.end_time,
    )
    original = item.model_dump(mode="json")

    context = build_evidence_context(incident, [item])[0]

    if expected_kind is None:
        assert context.metric_interpretation is None
    else:
        assert context.metric_interpretation is not None
        assert context.metric_interpretation.kind == expected_kind
        assert context.metric_interpretation.limitations
    assert item.model_dump(mode="json") == original
