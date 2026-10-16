import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Self

import pytest

from ai_incident_investigator.evaluation.dataset import load_dataset
from ai_incident_investigator.evaluation.live import LiveEvaluationRun
from ai_incident_investigator.investigations.analysis import Analysis, AnalysisError
from ai_incident_investigator.investigations.reports import Evidence, RecommendedCheck
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from scripts import evaluate_llm as cli

DATASET_PATH = Path(__file__).resolve().parents[1] / "evals" / "scenarios.json"
FAKE_KEY = "test-only-never-a-real-api-key"


class StubAnalyzer:
    def __init__(self) -> None:
        self.fail = False
        self.interrupt_after: int | None = None
        self.calls = 0

    def analyze(
        self,
        request: InvestigationRequest,
        evidence: Sequence[Evidence],
        missing_data: Sequence[str],
    ) -> Analysis:
        if self.interrupt_after == self.calls:
            raise KeyboardInterrupt

        self.calls += 1
        if self.fail:
            raise AnalysisError(FAKE_KEY)

        return Analysis(
            summary="Recorded evidence requires further investigation.",
            findings=[],
            hypotheses=[],
            recommended_checks=[
                RecommendedCheck(action="Review the evidence.", reason="The cause is uncertain.")
            ],
        )


@pytest.fixture
def fake_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict[str, object]], StubAnalyzer]:
    clients: list[dict[str, object]] = []
    analyzer = StubAnalyzer()

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            clients.append(kwargs)

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            pass

    def create_analyzer(client: object, model: str) -> StubAnalyzer:
        return analyzer

    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.setattr(cli, "OpenAI", FakeClient)
    monkeypatch.setattr(cli, "OpenAIAnalyzer", create_analyzer)
    return clients, analyzer


def arguments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *extra: str,
    allow_live: bool = True,
) -> Path:
    output = tmp_path / "results" / "run.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate-llm",
            *(["--allow-live"] if allow_live else []),
            "--model",
            "test-model",
            "--dataset",
            str(DATASET_PATH),
            "--output",
            str(output),
            *extra,
        ],
    )
    return output


def test_explicit_opt_in_is_required_before_loading_data_or_creating_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_provider: tuple[list[dict[str, object]], StubAnalyzer],
) -> None:
    output = arguments(monkeypatch, tmp_path, allow_live=False)

    def forbidden(path: Path) -> None:
        pytest.fail("The dataset must not be loaded before explicit opt-in")

    monkeypatch.setattr(cli, "load_dataset", forbidden)
    with pytest.raises(SystemExit, match="2"):
        cli.main()

    assert not output.exists()
    assert fake_provider[0] == []


def test_key_is_read_only_from_process_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_provider: tuple[list[dict[str, object]], StubAnalyzer],
) -> None:
    output = arguments(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={FAKE_KEY}\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="2"):
        cli.main()

    assert not output.exists()
    assert fake_provider[0] == []


@pytest.mark.parametrize("destination", ["sentinel", "dataset", "fixture"])
def test_existing_output_is_refused_before_creating_client(
    destination: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_provider: tuple[list[dict[str, object]], StubAnalyzer],
) -> None:
    sentinel = tmp_path / "existing.json"
    sentinel.write_text("keep this file", encoding="utf-8")
    dataset = load_dataset(DATASET_PATH)
    output = {
        "sentinel": sentinel,
        "dataset": DATASET_PATH,
        "fixture": DATASET_PATH.parent / "fixtures" / dataset.scenarios[0].log_file,
    }[destination]
    before = output.read_bytes()
    arguments(monkeypatch, tmp_path, "--output", str(output))

    with pytest.raises(SystemExit, match="FileExistsError"):
        cli.main()

    assert output.read_bytes() == before
    assert fake_provider[0] == []


def test_success_saves_all_cases_and_uses_fixed_provider_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fake_provider: tuple[list[dict[str, object]], StubAnalyzer],
) -> None:
    output = arguments(monkeypatch, tmp_path, "--revision", "abc123")
    cli.main()

    saved = LiveEvaluationRun.model_validate_json(output.read_bytes())
    assert saved.passed and saved.completed
    assert len(saved.results) == 4 and saved.total_calls == 3
    assert saved.model == "test-model" and saved.code_revision == "abc123"
    assert saved.semantic_quality == "pending_manual_review"
    assert fake_provider[0] == [
        {
            "api_key": FAKE_KEY,
            "base_url": "https://api.openai.com/v1",
            "timeout": 20.0,
            "max_retries": 0,
        }
    ]
    assert "pending manual review" in capsys.readouterr().out
    assert FAKE_KEY not in output.read_text(encoding="utf-8")


def test_failed_analysis_is_saved_without_exception_text_and_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    fake_provider: tuple[list[dict[str, object]], StubAnalyzer],
) -> None:
    output = arguments(monkeypatch, tmp_path)
    fake_provider[1].fail = True

    with pytest.raises(SystemExit, match="1"):
        cli.main()

    saved = LiveEvaluationRun.model_validate_json(output.read_bytes())
    assert saved.completed and not saved.passed
    assert saved.total_calls == 3
    assert any(item.error == "analysis_failed" for item in saved.results)
    captured = capsys.readouterr()
    assert FAKE_KEY not in captured.out + captured.err + caplog.text
    assert FAKE_KEY not in output.read_text(encoding="utf-8")


def test_interruption_keeps_latest_completed_cases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_provider: tuple[list[dict[str, object]], StubAnalyzer],
) -> None:
    output = arguments(monkeypatch, tmp_path)
    fake_provider[1].interrupt_after = 1

    with pytest.raises(KeyboardInterrupt):
        cli.main()

    saved = LiveEvaluationRun.model_validate_json(output.read_bytes())
    assert not saved.completed
    assert len(saved.results) == 2 and all(case.passed for case in saved.results)
    assert saved.total_calls == 1
    assert list(output.parent.glob(".*.tmp")) == []


def test_local_errors_print_only_exception_class(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_provider: tuple[list[dict[str, object]], StubAnalyzer],
) -> None:
    arguments(monkeypatch, tmp_path)

    def fail(path: Path) -> None:
        raise ValueError(FAKE_KEY)

    monkeypatch.setattr(cli, "load_dataset", fail)
    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert str(exc.value) == "Live evaluation failed: ValueError"
    assert FAKE_KEY not in str(exc.value)
    assert fake_provider[0] == []


@pytest.mark.parametrize(
    "extra",
    [
        ("--model", " "),
        ("--model", "x" * 101),
        ("--repeats", "4"),
        ("--max-calls", "11"),
    ],
)
def test_invalid_arguments_do_not_create_clients(
    extra: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_provider: tuple[list[dict[str, object]], StubAnalyzer],
) -> None:
    output = arguments(monkeypatch, tmp_path, *extra)

    with pytest.raises(SystemExit, match="2"):
        cli.main()

    assert not output.exists()
    assert fake_provider[0] == []
