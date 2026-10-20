import shutil
import sys
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from ai_incident_investigator import dependencies
from ai_incident_investigator.evaluation.dataset import (
    Dataset,
    Scenario,
    fixture_path,
    load_dataset,
)
from ai_incident_investigator.evaluation.runner import (
    EvaluationRun,
    RecordedActuatorCollector,
    RecordedMetricsCollector,
    grade_report,
    run_evaluation,
    run_scenario,
)
from ai_incident_investigator.investigations.reports import EvidenceSource
from ai_incident_investigator.llm import openai_client
from scripts import evaluate_investigations as cli

DATASET_PATH = Path(__file__).resolve().parents[1] / "evals" / "scenarios.json"
FIXTURES_DIR = DATASET_PATH.parent / "fixtures"


@pytest.fixture
def dataset() -> Dataset:
    return load_dataset(DATASET_PATH)


@pytest.fixture
def scenario(dataset: Dataset) -> Scenario:
    return next(item for item in dataset.scenarios if item.actuator and item.actuator.evidence)


def test_four_scenarios_pass_without_network_or_llm(
    dataset: Dataset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Offline evaluation must not create network or LLM clients")

    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(dependencies, "OpenAI", forbidden)
    monkeypatch.setattr(
        openai_client.OpenAIAnalyzer,
        "analyze",
        forbidden,
    )

    result = run_evaluation(
        dataset,
        fixtures_dir=FIXTURES_DIR,
    )

    assert len(result.scenarios) == 4
    assert result.passed_scenarios == 4
    assert result.passed
    assert result.mode == "offline_pipeline"
    assert result.semantic_quality == "not_evaluated"

    assert all(
        item.report and item.report.analysis_status == "not_requested" for item in result.scenarios
    )


@pytest.mark.parametrize(
    ("mutation", "failed_check"),
    [
        ("delete-evidence", "evidence_ids"),
        ("erase-gaps", "data_gaps"),
        ("backdate-snapshot", "recorded_observations"),
        ("rewrite-snapshot", "recorded_observations"),
        ("log-summary", "logs_preserved"),
        ("log-reference", "logs_preserved"),
        ("log-source", "logs_preserved"),
    ],
)
def test_grader_detects_report_regressions(
    scenario: Scenario,
    mutation: str,
    failed_check: str,
) -> None:
    report = run_scenario(
        scenario,
        fixtures_dir=FIXTURES_DIR,
    ).report

    assert report is not None
    report = report.model_copy(deep=True)

    if mutation == "delete-evidence":
        report.evidence.pop()
    elif mutation == "erase-gaps":
        report.missing_data.clear()
    elif mutation.startswith("log-"):
        log = next(item for item in report.evidence if item.source == EvidenceSource.LOG)

        if mutation == "log-summary":
            log.summary = "Incorrect error description"
        elif mutation == "log-reference":
            log.reference = "local-jsonl:line:999"
        else:
            log.source = EvidenceSource.METRIC
    else:
        snapshot = next(item for item in report.evidence if item.source == EvidenceSource.ACTUATOR)

        if mutation == "backdate-snapshot":
            snapshot.start_time = scenario.request.start_time
        else:
            snapshot.summary = "Rewritten snapshot"

    checks = {item.name: item.passed for item in grade_report(scenario, report)}

    assert checks[failed_check] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "service",
        "snapshot-end",
        "path-traversal",
        "duplicate-id",
    ],
)
def test_scenario_rejects_invalid_recordings(
    scenario: Scenario,
    mutation: str,
) -> None:
    payload = scenario.model_dump(mode="json")
    snapshot = payload["actuator"]["evidence"][0]

    if mutation == "source":
        snapshot["source"] = "log"
    elif mutation == "service":
        snapshot["service"] = "different-service"
    elif mutation == "snapshot-end":
        snapshot["end_time"] = (
            (scenario.actuator.evidence[0].start_time + timedelta(seconds=1)).isoformat()
            if scenario.actuator
            else None
        )
    elif mutation == "path-traversal":
        payload["log_file"] = "../outside.jsonl"
    else:
        snapshot["id"] = payload["expected"]["log_evidence"][0]["id"]

    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_dataset_rejects_duplicate_scenarios_and_expected_ids(
    scenario: Scenario,
) -> None:
    payload = scenario.model_dump(mode="json")

    with pytest.raises(ValidationError):
        Dataset.model_validate(
            {
                "version": 1,
                "scenarios": [payload, payload],
            }
        )

    log = payload["expected"]["log_evidence"][0]
    payload["expected"]["log_evidence"] = [log, log]

    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


@pytest.mark.parametrize("symlink", [False, True])
def test_missing_or_escaped_fixture_is_rejected(
    scenario: Scenario,
    tmp_path: Path,
    symlink: bool,
) -> None:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()

    if symlink:
        outside = tmp_path / "outside.jsonl"
        outside.write_text("{}\n", encoding="utf-8")

        (fixtures / scenario.log_file).symlink_to(outside)

    with pytest.raises(
        ValueError,
        match="Missing or invalid log fixture",
    ):
        fixture_path(fixtures, scenario)


def test_recorded_collectors_return_independent_copies(
    scenario: Scenario,
) -> None:
    assert scenario.metrics is not None
    assert scenario.actuator is not None

    original = scenario.model_dump()

    for collector in (
        RecordedMetricsCollector(scenario.metrics),
        RecordedActuatorCollector(scenario.actuator),
    ):
        first = collector.collect(scenario.request)

        first.evidence.clear()
        first.issues.append("Changed after collection")

        second = collector.collect(scenario.request)

        assert second.evidence
        assert "Changed after collection" not in second.issues

    assert scenario.model_dump() == original


def test_failed_cli_run_saves_report_and_exits_one(
    dataset: Dataset,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = dataset.model_copy(deep=True)
    broken.scenarios[0].expected.log_evidence.clear()

    output = tmp_path / "results" / "evaluation.json"

    monkeypatch.setattr(
        cli,
        "load_dataset",
        lambda _: broken,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate",
            "--dataset",
            str(DATASET_PATH),
            "--output",
            str(output),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1

    saved = EvaluationRun.model_validate_json(output.read_text(encoding="utf-8"))

    assert not saved.passed
    assert any(not check.passed for check in saved.scenarios[0].checks)


@pytest.mark.parametrize("overwrite", ["dataset", "fixture"])
def test_cli_does_not_overwrite_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overwrite: str,
) -> None:
    path = tmp_path / "scenarios.json"
    path.write_bytes(DATASET_PATH.read_bytes())

    fixtures = tmp_path / "fixtures"
    shutil.copytree(FIXTURES_DIR, fixtures)

    dataset = load_dataset(path)

    output = path if overwrite == "dataset" else fixture_path(fixtures, dataset.scenarios[0])

    before = output.read_bytes()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate",
            "--dataset",
            str(path),
            "--output",
            str(output),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code != 0
    assert output.read_bytes() == before
