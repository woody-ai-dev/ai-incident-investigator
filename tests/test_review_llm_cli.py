import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_incident_investigator.evaluation.live import LiveCaseResult, LiveEvaluationRun
from ai_incident_investigator.evaluation.review import (
    ReviewStatus,
    RunReview,
    Verdict,
    create_review,
    evaluate_review,
    load_run,
)
from ai_incident_investigator.evaluation.runner import CheckResult
from ai_incident_investigator.investigations.reports import (
    Evidence,
    EvidenceSource,
    InvestigationReport,
)
from scripts import review_llm as cli


@pytest.fixture
def source_run(tmp_path: Path) -> Path:
    observed_at = datetime(2026, 10, 16, 12, tzinfo=UTC)
    report = InvestigationReport(
        analysis_status="completed",
        summary="A simulated timeout was recorded; its underlying cause is unknown.",
        evidence=[
            Evidence(
                id="log-1",
                source=EvidenceSource.LOG,
                service="order-service",
                summary="[ERROR] Payment request timed out (simulated).",
                reference="fixture:timeout:1",
                start_time=observed_at,
            )
        ],
        findings=[],
        hypotheses=[],
        recommended_checks=[],
        missing_data=[],
    )
    run = LiveEvaluationRun(
        model="test-model",
        prompt_sha256="a" * 64,
        dataset_sha256="b" * 64,
        dataset_version=1,
        created_at=observed_at,
        repeats=1,
        max_calls=1,
        completed=True,
        results=[
            LiveCaseResult(
                scenario_id="simulated-timeout",
                repeat=1,
                calls=1,
                duration_ms=1,
                report=report,
                checks=[CheckResult(name="fixture", passed=True, description="Synthetic check.")],
                review_questions=["Are conclusions supported by the simulated observation?"],
            )
        ],
    )
    path = tmp_path / "run.json"
    path.write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def invoke(monkeypatch: pytest.MonkeyPatch, *arguments: str) -> None:
    monkeypatch.setattr(sys, "argv", ["review-llm", *arguments])
    cli.main()


def test_init_creates_pending_template_without_changing_source(
    source_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = source_run.read_bytes()
    output = source_run.parent / "reviews" / "review.json"
    invoke(monkeypatch, "init", "--run", str(source_run), "--output", str(output))

    run, digest = load_run(source_run)
    review = RunReview.model_validate_json(output.read_bytes())
    assert review.reviewer == ""
    assert all(
        verdict == Verdict.NOT_REVIEWED for case in review.cases for verdict in case.verdicts
    )
    assert evaluate_review(run, review, source_sha256=digest) == ReviewStatus.PENDING
    assert source_run.read_bytes() == original


@pytest.mark.parametrize("destination", ["source", "existing"])
def test_init_refuses_to_overwrite_any_existing_file(
    source_run: Path, monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    output = source_run if destination == "source" else source_run.parent / "review.json"
    if destination == "existing":
        output.write_bytes(b"Keep this existing review.")
    original_source, original_output = source_run.read_bytes(), output.read_bytes()

    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, "init", "--run", str(source_run), "--output", str(output))

    assert exc.value.code == 2
    assert source_run.read_bytes() == original_source
    assert output.read_bytes() == original_output


@pytest.mark.parametrize(("state", "exit_code"), [("pending", 1), ("approved", 0), ("changed", 2)])
def test_check_recomputes_status_without_modifying_files(
    source_run: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    state: str,
    exit_code: int,
) -> None:
    run, digest = load_run(source_run)
    payload = create_review(run, source_sha256=digest).model_dump(mode="json")
    if state == "approved":
        payload["reviewer"] = "Test engineer"
        for case in payload["cases"]:
            for criterion in (
                "evidence_support",
                "causal_reasoning",
                "data_limitations",
                "next_checks",
            ):
                case[criterion] = "pass"
            case["notes"] = "The saved response preserves simulation and uncertainty."
    review_path = source_run.parent / "review.json"
    review_path.write_text(RunReview.model_validate(payload).model_dump_json(), encoding="utf-8")
    if state == "changed":
        source_run.write_bytes(source_run.read_bytes() + b"\n")
    before = {path: path.read_bytes() for path in (source_run, review_path)}

    if exit_code:
        with pytest.raises(SystemExit) as exc:
            invoke(monkeypatch, "check", "--run", str(source_run), "--review", str(review_path))
        assert exc.value.code == exit_code
    else:
        invoke(monkeypatch, "check", "--run", str(source_run), "--review", str(review_path))

    captured = capsys.readouterr()
    if state == "changed":
        assert captured.err == "Review failed: ValueError\n"
    else:
        assert ("reviewed_pass" if state == "approved" else "pending_review") in captured.out
    assert {path: path.read_bytes() for path in before} == before
