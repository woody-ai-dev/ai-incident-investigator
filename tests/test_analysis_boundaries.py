import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_incident_investigator.investigations.analysis import Analysis
from ai_incident_investigator.investigations.evidence_context import (
    validate_hypothesis_time_support,
)
from ai_incident_investigator.investigations.reports import (
    Evidence,
    EvidenceSource,
    Finding,
    Hypothesis,
    InvestigationReport,
    RecommendedCheck,
)
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.investigations.service import investigate
from ai_incident_investigator.sources.context import ActuatorCollection


@pytest.fixture
def incident() -> InvestigationRequest:
    return InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=datetime(2026, 10, 18, 10, tzinfo=UTC),
        end_time=datetime(2026, 10, 18, 10, 5, tzinfo=UTC),
    )


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    path = tmp_path / "logs.jsonl"
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-10-18T10:02:00Z",
                "service": "order-service",
                "environment": "local",
                "level": "ERROR",
                "message": "Payment request timed out (simulated).",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def snapshot(incident: InvestigationRequest, *, minutes: int = 6) -> Evidence:
    return Evidence(
        id="actuator-health",
        source=EvidenceSource.ACTUATOR,
        service=incident.service,
        summary="The health endpoint reported UP at its observation time.",
        reference="fixture:actuator-health",
        start_time=incident.start_time + timedelta(minutes=minutes),
    )


def analysis(
    *,
    supporting: Sequence[str] = (),
    contradicting: Sequence[str] = (),
    finding_ids: Sequence[str] = (),
) -> Analysis:
    return Analysis(
        summary="Synthetic analysis for testing reference and time boundaries.",
        findings=(
            [
                Finding(
                    statement="A later endpoint snapshot reported UP.",
                    evidence_ids=list(finding_ids),
                )
            ]
            if finding_ids
            else []
        ),
        hypotheses=(
            [
                Hypothesis(
                    statement="A possible incident explanation requiring review.",
                    supporting_evidence_ids=list(supporting),
                    contradicting_evidence_ids=list(contradicting),
                )
            ]
            if supporting
            else []
        ),
        recommended_checks=[
            RecommendedCheck(
                action="Inspect retained incident observations, if available.",
                reason="The cause remains unverified.",
            )
        ],
    )


class StubActuatorCollector:
    def __init__(self, evidence: list[Evidence]) -> None:
        self.evidence = evidence

    def collect(self, request: InvestigationRequest) -> ActuatorCollection:
        return ActuatorCollection(
            evidence=self.evidence,
            issues=["Actuator snapshots are observations at their recorded times."],
        )


class StubAnalyzer:
    def __init__(self, result: Analysis) -> None:
        self.result = result
        self.calls = 0

    def analyze(
        self,
        request: InvestigationRequest,
        evidence: Sequence[Evidence],
        missing_data: Sequence[str],
    ) -> Analysis:
        self.calls += 1
        return self.result


@pytest.mark.parametrize(
    ("minutes", "expected_status"),
    [(-1, "failed"), (0, "completed"), (4, "completed"), (5, "failed"), (6, "failed")],
)
def test_snapshot_support_respects_inclusive_start_and_exclusive_end(
    incident: InvestigationRequest,
    log_path: Path,
    minutes: int,
    expected_status: str,
) -> None:
    collector = StubActuatorCollector([snapshot(incident, minutes=minutes)])
    analyzer = StubAnalyzer(analysis(supporting=["actuator-health"]))

    report = investigate(
        incident, log_path=log_path, actuator_collector=collector, analyzer=analyzer
    )

    assert analyzer.calls == 1
    assert report.analysis_status == expected_status
    assert {item.id for item in report.evidence} == {"log-1", "actuator-health"}
    assert bool(report.hypotheses) == (expected_status == "completed")


def test_rejected_analysis_retains_complete_fallback(
    incident: InvestigationRequest, log_path: Path
) -> None:
    collector = StubActuatorCollector([snapshot(incident)])
    baseline = investigate(incident, log_path=log_path, actuator_collector=collector)
    report = investigate(
        incident,
        log_path=log_path,
        actuator_collector=collector,
        analyzer=StubAnalyzer(
            analysis(supporting=["actuator-health"], finding_ids=["actuator-health"])
        ),
    )

    assert report.analysis_status == "failed"
    assert report.evidence == baseline.evidence
    assert report.summary == baseline.summary
    assert report.findings == []
    assert report.hypotheses == []
    assert report.recommended_checks == baseline.recommended_checks
    assert report.missing_data[:-1] == baseline.missing_data
    assert "collected evidence has been retained" in report.missing_data[-1]


def test_late_snapshot_remains_valid_for_a_finding(
    incident: InvestigationRequest, log_path: Path
) -> None:
    report = investigate(
        incident,
        log_path=log_path,
        actuator_collector=StubActuatorCollector([snapshot(incident)]),
        analyzer=StubAnalyzer(analysis(finding_ids=["actuator-health"])),
    )

    assert report.analysis_status == "completed"
    assert report.findings[0].evidence_ids == ["actuator-health"]
    assert report.hypotheses == []


@pytest.mark.parametrize(
    ("supporting", "contradicting", "expected_status"),
    [
        (["actuator-health", "log-1"], [], "completed"),
        (["actuator-health"], ["log-1"], "failed"),
        (["log-1"], ["actuator-health"], "completed"),
    ],
)
def test_only_positive_references_count_as_support(
    incident: InvestigationRequest,
    log_path: Path,
    supporting: list[str],
    contradicting: list[str],
    expected_status: str,
) -> None:
    report = investigate(
        incident,
        log_path=log_path,
        actuator_collector=StubActuatorCollector([snapshot(incident)]),
        analyzer=StubAnalyzer(analysis(supporting=supporting, contradicting=contradicting)),
    )

    # Completion means the narrow structural rule passed, not that the claim is true.
    assert report.analysis_status == expected_status


def test_multiple_outside_snapshots_do_not_create_incident_support(
    incident: InvestigationRequest, log_path: Path
) -> None:
    earlier = snapshot(incident, minutes=-1).model_copy(update={"id": "actuator-earlier"})
    later = snapshot(incident)
    report = investigate(
        incident,
        log_path=log_path,
        actuator_collector=StubActuatorCollector([earlier, later]),
        analyzer=StubAnalyzer(analysis(supporting=[earlier.id, later.id])),
    )

    assert report.analysis_status == "failed"
    assert len(report.evidence) == 3


@pytest.mark.parametrize("reference_kind", ["finding", "supporting", "contradicting"])
def test_unknown_references_are_rejected_before_time_lookup(
    incident: InvestigationRequest, log_path: Path, reference_kind: str
) -> None:
    result = analysis(
        finding_ids=["unknown-id"] if reference_kind == "finding" else [],
        supporting=["unknown-id"] if reference_kind == "supporting" else ["log-1"],
        contradicting=["unknown-id"] if reference_kind == "contradicting" else [],
    )
    report = investigate(
        incident,
        log_path=log_path,
        actuator_collector=StubActuatorCollector([snapshot(incident)]),
        analyzer=StubAnalyzer(result),
    )

    assert report.analysis_status == "failed"
    assert len(report.evidence) == 2
    assert report.findings == []
    assert report.hypotheses == []


def test_preincident_log_is_not_rejected_by_snapshot_policy(incident: InvestigationRequest) -> None:
    preceding_log = snapshot(incident, minutes=-1).model_copy(
        update={"id": "preceding-log", "source": EvidenceSource.LOG}
    )
    candidate = InvestigationReport(
        analysis_status="completed",
        evidence=[preceding_log],
        missing_data=[],
        **analysis(supporting=[preceding_log.id]).model_dump(),
    )

    validate_hypothesis_time_support(incident, candidate)

    assert candidate.analysis_status == "completed"


@pytest.mark.parametrize(("start_minutes", "end_minutes"), [(-2, -1), (-1, 1), (6, 7)])
def test_interval_actuator_observations_are_outside_point_snapshot_policy(
    incident: InvestigationRequest, start_minutes: int, end_minutes: int
) -> None:
    interval = snapshot(incident, minutes=start_minutes).model_copy(
        update={"end_time": incident.start_time + timedelta(minutes=end_minutes)}
    )
    candidate = InvestigationReport(
        analysis_status="completed",
        evidence=[interval],
        missing_data=[],
        **analysis(supporting=[interval.id]).model_dump(),
    )

    # Future interval sources need an explicit policy; they are not point snapshots.
    validate_hypothesis_time_support(incident, candidate)

    assert candidate.analysis_status == "completed"
