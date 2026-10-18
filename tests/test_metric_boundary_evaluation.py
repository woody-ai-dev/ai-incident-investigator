import sys
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path

import httpx
import httpx2
import pytest

from ai_incident_investigator.evaluation.dataset import Dataset, load_dataset
from ai_incident_investigator.evaluation.live import run_live_evaluation
from ai_incident_investigator.evaluation.review import (
    ReviewStatus,
    create_review,
    evaluate_review,
)
from ai_incident_investigator.evaluation.runner import EvaluationRun, run_evaluation, run_scenario
from ai_incident_investigator.investigations.analysis import Analysis
from ai_incident_investigator.investigations.reports import (
    Evidence,
    EvidenceSource,
    RecommendedCheck,
)
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.llm import dependencies, openai_client
from scripts import evaluate_investigations as cli

DATASET_PATH = Path(__file__).resolve().parents[1] / "evals" / "metric-boundaries.json"
FIXTURES_DIR = DATASET_PATH.parent / "fixtures"

EXPECTED_IDS = {
    "scrape-success-business-failure": {
        "log-1",
        "metric-up",
        "actuator-info",
        "actuator-health",
    },
    "heap-without-baseline": {"metric-jvm-heap"},
    "counter-drop-without-raw-series": {"metric-http-504-counter"},
    "sparse-scrapes-with-failure": {"metric-up"},
}


@pytest.fixture
def dataset() -> Dataset:
    return load_dataset(DATASET_PATH)


class StubAnalyzer:
    def __init__(self) -> None:
        self.calls = 0

    def analyze(
        self,
        request: InvestigationRequest,
        evidence: Sequence[Evidence],
        missing_data: Sequence[str],
    ) -> Analysis:
        self.calls += 1
        assert evidence
        return Analysis(
            summary="Synthetic test response; semantic quality is not evaluated.",
            findings=[],
            hypotheses=[],
            recommended_checks=[
                RecommendedCheck(
                    action="Review the original observations.",
                    reason="This stub checks pipeline integration only.",
                )
            ],
        )


def test_metric_suite_runs_without_network_or_model_clients(
    dataset: Dataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Offline metric evaluation must not use network or model clients")

    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(httpx2, "Client", forbidden)
    monkeypatch.setattr(dependencies, "OpenAI", forbidden)
    monkeypatch.setattr(openai_client.OpenAIAnalyzer, "analyze", forbidden)

    result = run_evaluation(dataset, fixtures_dir=FIXTURES_DIR)

    assert result.passed and result.passed_scenarios == 4
    assert result.semantic_quality == "not_evaluated"
    assert {case.scenario_id for case in result.scenarios} == set(EXPECTED_IDS)


@pytest.mark.parametrize("scenario_id", EXPECTED_IDS)
def test_each_case_preserves_its_required_observations(dataset: Dataset, scenario_id: str) -> None:
    scenario = next(item for item in dataset.scenarios if item.id == scenario_id)
    result = run_scenario(scenario, fixtures_dir=FIXTURES_DIR)

    assert result.passed and result.report is not None
    assert {item.id for item in result.report.evidence} == EXPECTED_IDS[scenario_id]
    assert result.report.analysis_status == "not_requested"
    assert not result.report.findings and not result.report.hypotheses


def test_scrape_case_retains_timeout_and_late_snapshots(dataset: Dataset) -> None:
    scenario = next(
        item for item in dataset.scenarios if item.id == "scrape-success-business-failure"
    )
    report = run_scenario(scenario, fixtures_dir=FIXTURES_DIR).report
    assert report is not None

    logs = [item for item in report.evidence if item.source == EvidenceSource.LOG]
    snapshots = [item for item in report.evidence if item.source == EvidenceSource.ACTUATOR]

    assert len(logs) == 1 and "timed out (simulated)" in logs[0].summary
    assert len(snapshots) == 2
    assert all(item.start_time >= scenario.request.end_time for item in snapshots)
    assert all(item.end_time is None for item in snapshots)
    assert any("outside the requested incident window" in issue for issue in report.missing_data)


def test_sparse_case_keeps_explicit_coverage_gap(dataset: Dataset) -> None:
    scenario = next(item for item in dataset.scenarios if item.id == "sparse-scrapes-with-failure")
    report = run_scenario(scenario, fixtures_dir=FIXTURES_DIR).report
    assert report is not None
    assert any("2 of 60 expected evaluation samples" in issue for issue in report.missing_data)


def test_metric_suite_is_compatible_with_live_runner_and_review(dataset: Dataset) -> None:
    analyzer = StubAnalyzer()
    run = run_live_evaluation(
        dataset,
        fixtures_dir=FIXTURES_DIR,
        analyzer=analyzer,
        model="test-model",
        max_calls=4,
    )
    fingerprint = sha256(run.model_dump_json().encode("utf-8")).hexdigest()
    review = create_review(run, source_sha256=fingerprint)

    assert run.passed and analyzer.calls == run.total_calls == 4
    assert run.semantic_quality == "pending_manual_review"
    assert {case.scenario_id for case in review.cases} == set(EXPECTED_IDS)
    assert evaluate_review(run, review, source_sha256=fingerprint) == ReviewStatus.PENDING


def test_insufficient_budget_is_rejected_before_any_analysis(dataset: Dataset) -> None:
    analyzer = StubAnalyzer()

    with pytest.raises(ValueError, match="needs up to 4 calls"):
        run_live_evaluation(
            dataset,
            fixtures_dir=FIXTURES_DIR,
            analyzer=analyzer,
            model="test-model",
            max_calls=3,
        )

    assert analyzer.calls == 0


def test_existing_cli_can_select_the_metric_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "metric-results.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluate", "--dataset", str(DATASET_PATH), "--output", str(output)],
    )

    cli.main()
    saved = EvaluationRun.model_validate_json(output.read_bytes())

    assert saved.passed and saved.passed_scenarios == 4
    assert {case.scenario_id for case in saved.scenarios} == set(EXPECTED_IDS)
