import hashlib
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from ai_incident_investigator.evaluation.dataset import Dataset, load_dataset
from ai_incident_investigator.evaluation.live import (
    LiveEvaluationRun,
    run_live_evaluation,
)
from ai_incident_investigator.evaluation.runner import run_scenario
from ai_incident_investigator.investigations.analysis import Analysis, AnalysisError
from ai_incident_investigator.investigations.reports import (
    Evidence,
    Finding,
    RecommendedCheck,
)
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.llm.prompts import SUMMARY_MAX_WORDS, SYSTEM_PROMPT

DATASET_PATH = Path(__file__).resolve().parents[1] / "evals" / "scenarios.json"
FIXTURES_DIR = DATASET_PATH.parent / "fixtures"


@pytest.fixture
def dataset() -> Dataset:
    return load_dataset(DATASET_PATH)


class StubAnalyzer:
    def __init__(
        self,
        mode: str = "success",
        summary: str = "Collected observations require further investigation.",
    ) -> None:
        self.mode = mode
        self.calls = 0
        self.summary = summary

    def analyze(
        self,
        request: InvestigationRequest,
        evidence: Sequence[Evidence],
        missing_data: Sequence[str],
    ) -> Analysis:
        self.calls += 1
        assert evidence

        if self.mode == "error":
            raise AnalysisError("Synthetic provider failure")

        return Analysis(
            summary=self.summary,
            findings=[
                Finding(
                    statement="An observation was collected.",
                    evidence_ids=["invented-id" if self.mode == "unknown-id" else evidence[0].id],
                )
            ],
            hypotheses=[],
            recommended_checks=[
                RecommendedCheck(
                    action="Review the original source.",
                    reason="The observations do not establish a root cause.",
                )
            ],
        )


def test_success_preserves_observations_and_skips_empty_case(dataset: Dataset) -> None:
    analyzer = StubAnalyzer()
    original = dataset.model_dump(mode="json")
    result = run_live_evaluation(
        dataset,
        fixtures_dir=FIXTURES_DIR,
        analyzer=analyzer,
        model="test-model",
        code_revision="test-revision",
    )

    assert result.completed and result.passed
    assert result.mode == "live_model"
    assert result.semantic_quality == "pending_manual_review"
    assert result.provider == "openai"
    assert result.model == "test-model"
    assert result.code_revision == "test-revision"
    assert result.created_at.utcoffset() is not None
    assert analyzer.calls == result.total_calls == 3
    assert len(result.results) == 4
    assert dataset.model_dump(mode="json") == original

    for scenario, case in zip(dataset.scenarios, result.results, strict=True):
        baseline = run_scenario(scenario, fixtures_dir=FIXTURES_DIR).report
        assert baseline is not None and case.report is not None
        assert case.scenario_id == scenario.id and case.repeat == 1
        assert case.report.evidence == baseline.evidence
        assert set(baseline.missing_data) <= set(case.report.missing_data)
        assert case.review_questions == scenario.review_questions
        assert case.duration_ms >= 0 and case.error is None and case.passed
        assert case.calls == bool(baseline.evidence)
        assert case.report.analysis_status == ("completed" if baseline.evidence else "skipped")

        if not baseline.evidence:
            assert not case.report.findings and not case.report.hypotheses


@pytest.mark.parametrize("word_count", [SUMMARY_MAX_WORDS, SUMMARY_MAX_WORDS + 1])
def test_live_evaluation_grades_summary_length_without_discarding_the_report(
    dataset: Dataset, word_count: int
) -> None:
    summary = " ".join(["observation"] * word_count)
    result = run_live_evaluation(
        dataset,
        fixtures_dir=FIXTURES_DIR,
        analyzer=StubAnalyzer(summary=summary),
        model="test-model",
    )
    for case in result.results:
        assert case.report is not None
        check = next(check for check in case.checks if check.name == "summary_concise")
        assert check.passed == (case.calls == 0 or word_count <= SUMMARY_MAX_WORDS)
        if case.calls:
            assert case.report.analysis_status == "completed"
            assert case.report.summary == summary
    assert result.passed == (word_count <= SUMMARY_MAX_WORDS)


def test_readability_scenario_preserves_lifecycle_logs_and_metric_context() -> None:
    dataset = load_dataset(DATASET_PATH.with_name("report-readability.json"))
    result = run_live_evaluation(
        dataset, fixtures_dir=FIXTURES_DIR, analyzer=StubAnalyzer(), model="test-model"
    )
    assert result.passed and result.total_calls == 1
    report = result.results[0].report
    assert report is not None
    assert len(report.evidence) == 9
    assert any("Graceful shutdown complete" in item.summary for item in report.evidence)
    assert any(item.id == "metric-jvm-heap" for item in report.evidence)
    assert any("incomplete coverage" in issue for issue in report.missing_data)


@pytest.mark.parametrize(
    ("summary", "passed"),
    [
        ("Service logs record a restart; the cause remains unknown.", True),
        ("Prometheus reports 30.4 MB of heap usage. Memory pressure remains unknown.", True),
        ("Logs record a restart. Metrics report heap usage. The cause remains unknown.", False),
    ],
)
def test_live_evaluation_checks_sentence_limit_without_splitting_decimal_values(
    dataset: Dataset, summary: str, passed: bool
) -> None:
    result = run_live_evaluation(
        dataset,
        fixtures_dir=FIXTURES_DIR,
        analyzer=StubAnalyzer(summary=summary),
        model="test-model",
    )
    for case in result.results:
        check = next(check for check in case.checks if check.name == "summary_sentence_limit")
        assert check.passed == (case.calls == 0 or passed)


@pytest.mark.parametrize("mode", ["error", "unknown-id"])
def test_failed_analysis_is_counted_and_fallback_remains_inspectable(
    dataset: Dataset, mode: str
) -> None:
    analyzer = StubAnalyzer(mode)
    result = run_live_evaluation(
        dataset, fixtures_dir=FIXTURES_DIR, analyzer=analyzer, model="test-model"
    )

    assert result.completed and not result.passed
    assert analyzer.calls == result.total_calls == 3

    for scenario, case in zip(dataset.scenarios, result.results, strict=True):
        baseline = run_scenario(scenario, fixtures_dir=FIXTURES_DIR).report
        assert baseline is not None and case.report is not None
        assert case.report.evidence == baseline.evidence
        assert set(baseline.missing_data) <= set(case.report.missing_data)

        if baseline.evidence:
            assert case.error == "analysis_failed" and not case.passed
            assert case.report.analysis_status == "failed" and case.calls == 1
            assert not case.report.findings and not case.report.hypotheses
            assert any("LLM analysis failed" in issue for issue in case.report.missing_data)
        else:
            assert case.passed and case.error is None and case.calls == 0


@pytest.mark.parametrize(("repeats", "max_calls"), [(0, 3), (4, 10), (1, 0), (1, 11), (2, 3)])
def test_invalid_limits_fail_before_any_analyzer_call(
    dataset: Dataset, repeats: int, max_calls: int
) -> None:
    analyzer = StubAnalyzer()

    with pytest.raises(ValueError):
        run_live_evaluation(
            dataset,
            fixtures_dir=FIXTURES_DIR,
            analyzer=analyzer,
            model="test-model",
            repeats=repeats,
            max_calls=max_calls,
        )

    assert analyzer.calls == 0


def test_repeated_runs_respect_the_total_call_budget(dataset: Dataset) -> None:
    analyzer = StubAnalyzer()
    result = run_live_evaluation(
        dataset,
        fixtures_dir=FIXTURES_DIR,
        analyzer=analyzer,
        model="test-model",
        repeats=3,
        max_calls=9,
    )

    assert result.passed and len(result.results) == 12
    assert analyzer.calls == result.total_calls == 9
    assert {(case.scenario_id, case.repeat) for case in result.results} == {
        (scenario.id, repeat) for scenario in dataset.scenarios for repeat in (1, 2, 3)
    }


@pytest.mark.parametrize("mutation", ["missing-fixture", "failed-expectation"])
def test_all_baselines_are_checked_before_any_model_call(dataset: Dataset, mutation: str) -> None:
    if mutation == "missing-fixture":
        dataset.scenarios[-1].log_file = "missing.jsonl"
    else:
        dataset.scenarios[-1].expected.missing_data_contains = ["Required but absent data gap"]

    analyzer = StubAnalyzer()

    with pytest.raises(ValueError):
        run_live_evaluation(
            dataset, fixtures_dir=FIXTURES_DIR, analyzer=analyzer, model="test-model"
        )

    assert analyzer.calls == 0


def test_fingerprints_include_prompt_and_fixture_bytes(dataset: Dataset, tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    shutil.copytree(FIXTURES_DIR, fixtures)
    before = run_live_evaluation(
        dataset, fixtures_dir=fixtures, analyzer=StubAnalyzer(), model="test-model"
    )
    path = fixtures / dataset.scenarios[0].log_file
    path.write_bytes(path.read_bytes() + b"\n")
    after = run_live_evaluation(
        dataset, fixtures_dir=fixtures, analyzer=StubAnalyzer(), model="test-model"
    )

    assert before.prompt_sha256 == hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    assert len(before.dataset_sha256) == len(after.dataset_sha256) == 64
    assert before.dataset_sha256 != after.dataset_sha256
    assert before.prompt_sha256 == after.prompt_sha256


def test_checkpoints_and_json_keep_partial_progress(dataset: Dataset) -> None:
    snapshots: list[LiveEvaluationRun] = []

    def checkpoint(run: LiveEvaluationRun) -> None:
        snapshots.append(LiveEvaluationRun.model_validate_json(run.model_dump_json()))

    result = run_live_evaluation(
        dataset,
        fixtures_dir=FIXTURES_DIR,
        analyzer=StubAnalyzer(),
        model="test-model",
        checkpoint=checkpoint,
    )

    assert [len(item.results) for item in snapshots] == [0, 1, 2, 3, 4, 4]
    assert not any(item.completed for item in snapshots[:-1])
    assert snapshots[-1] == result and snapshots[-1].completed
    assert not snapshots[0].passed
    assert LiveEvaluationRun.model_validate_json(result.model_dump_json()) == result
