import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO

import pytest

from ai_incident_investigator.knowledge.retrieval_context import KnowledgeContext
from scripts import run_knowledge_baseline as cli

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
FIXTURES = Path("fixtures/knowledge-recommendations")
COMPLETED = "simulated-payment-timeout"
SKIPPED = "no-eligible-scope"
ARTIFACT = ROOT / "tests/fixtures/knowledge/recommendations.json"


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    manifest = json.loads((EVALS / "knowledge-recommendations.json").read_bytes())
    by_id = {case["id"]: case for case in manifest["cases"]}
    manifest["cases"] = [by_id[COMPLETED], by_id[SKIPPED]]
    (tmp_path / FIXTURES).mkdir(parents=True)
    for case_id in (COMPLETED, SKIPPED):
        export = FIXTURES / f"{case_id}.json"
        (tmp_path / export).write_bytes((EVALS / export).read_bytes())
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def invoke(monkeypatch: pytest.MonkeyPatch, dataset: Path, output: Path) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_knowledge_baseline.py",
            "--dataset",
            str(dataset),
            "--output",
            str(output),
            "--include-drafts",
        ],
    )
    cli.main()


def install_child(monkeypatch: pytest.MonkeyPatch, problem: str | None = None) -> list[str]:
    calls: list[str] = []

    def child(
        command: list[str], *, cwd: Path, stdout: BinaryIO, stderr: BinaryIO, check: bool
    ) -> subprocess.CompletedProcess[bytes]:
        assert command[:2] == [sys.executable, str(ROOT / "scripts/recommend_knowledge.py")]
        assert cwd == ROOT
        assert not check
        assert "--include-drafts" in command

        def argument(flag: str) -> str:
            return command[command.index(flag) + 1]

        for flag, value in {
            "--model": "gpt-4.1-mini-2025-04-14",
            "--max-characters": "2000",
            "--limit": "10",
            "--context-max-chunks": "5",
            "--context-max-bytes": "12000",
        }.items():
            assert argument(flag) == value

        export_path = Path(argument("--investigation"))
        output = Path(str(stdout.name)).parents[2]
        assert export_path.parent == output / FIXTURES
        assert (output / "run.json").is_file()
        case_id = export_path.stem
        calls.append(case_id)
        if case_id == COMPLETED and problem == "empty_artifact":
            stderr.write(b"child error\n")
            return subprocess.CompletedProcess(command, 1)
        if case_id == COMPLETED and problem == "invalid_artifact":
            stdout.write(b"{}")
            return subprocess.CompletedProcess(command, 0)

        raw_export = export_path.read_bytes()
        export = json.loads(raw_export)
        artifact = json.loads(ARTIFACT.read_bytes())
        query = next(
            item.removeprefix("--query=") for item in command if item.startswith("--query=")
        )
        artifact.update(
            input_sha256=sha256(raw_export).hexdigest(),
            query=query,
            investigation=export,
            model=argument("--model"),
            mode="preview",
        )
        context = artifact["assembly"]["context"]
        context["mode"] = "preview"
        if case_id == SKIPPED:
            context.update(service=export["request"]["service"], chunks=[])
            artifact.update(
                status="skipped",
                collection=None,
                recommendations=None,
                generation_usage=None,
                issue="No eligible knowledge documents for the requested scope.",
            )
            if problem == "skip_usage":
                artifact["embedding_total_tokens"] = 1
            if problem == "mixed_prompts":
                artifact["prompt_sha256"] = "e" * 64
        else:
            artifact["generation_usage"]["requested_model"] = artifact["model"]
            artifact["recommendations"] = {
                "checks": [],
                "limitations": ["The selected reference does not cover the reported failure."],
            }
            if problem == "artifact_mismatch":
                artifact["input_sha256"] = "f" * 64
            if problem == "missing_collection":
                artifact["collection"] = None
            if problem == "unexpected_outcome":
                artifact.update(
                    status="failed",
                    recommendations=None,
                    generation_usage=None,
                    issue="Recommendation generation failed.",
                )
        artifact["assembly"]["payload_bytes"] = KnowledgeContext.model_validate(
            context
        ).payload_bytes
        stdout.write(json.dumps(artifact).encode("utf-8"))
        return subprocess.CompletedProcess(command, int(artifact["status"] == "failed"))

    monkeypatch.setattr(subprocess, "run", child)
    return calls


def test_saves_inputs_and_records_completed_and_skipped(
    dataset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "run"
    calls = install_child(monkeypatch)
    invoke(monkeypatch, dataset, output)

    assert calls == [COMPLETED, SKIPPED]
    assert (output / "dataset.json").read_bytes() == dataset.read_bytes()
    summary = json.loads(capsys.readouterr().out)
    assert summary == json.loads((output / "summary.json").read_bytes())
    for case, expected in zip(summary["cases"], ("completed", "skipped"), strict=True):
        case_id = case["case_id"]
        export = FIXTURES / f"{case_id}.json"
        case_dir = output / "cases" / case_id
        assert (output / export).read_bytes() == (dataset.parent / export).read_bytes()
        assert (case_dir / "recommendations.json").is_file()
        assert (case_dir / "stderr.txt").read_bytes() == b""
        assert (case_dir / "exit-code.txt").read_text(encoding="utf-8").strip() == "0"
        assert case["status"] == expected
        assert case["technical_expectation_met"] is True
        assert case["problem"] is None


@pytest.mark.parametrize(
    ("problem", "exit_code", "status", "reported_problem"),
    [
        ("empty_artifact", 1, None, "empty_artifact"),
        ("invalid_artifact", 0, None, "invalid_artifact"),
        ("artifact_mismatch", 0, None, "artifact_mismatch"),
        ("missing_collection", 0, "completed", "unexpected_outcome"),
        ("unexpected_outcome", 1, "failed", "unexpected_outcome"),
    ],
)
def test_preserves_failure_and_runs_remaining_case(
    dataset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
    exit_code: int,
    status: str | None,
    reported_problem: str,
) -> None:
    output = tmp_path / "run"
    calls = install_child(monkeypatch, problem)
    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, dataset, output)

    assert error.value.code == 1
    assert calls == [COMPLETED, SKIPPED]
    first, second = json.loads((output / "summary.json").read_bytes())["cases"]
    assert first["problem"] == reported_problem
    assert first["exit_code"] == exit_code
    assert first["status"] == status
    assert first["technical_expectation_met"] is False
    assert second["technical_expectation_met"] is True
    if problem == "empty_artifact":
        case_dir = output / "cases" / COMPLETED
        assert (case_dir / "recommendations.json").read_bytes() == b""
        assert (case_dir / "stderr.txt").read_bytes() == b"child error\n"


@pytest.mark.parametrize("problem", ["mixed_prompts", "skip_usage"])
def test_run_rejects_inconsistent_metadata(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    output = tmp_path / "run"
    install_child(monkeypatch, problem)
    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, dataset, output)

    assert error.value.code == 1
    summary = json.loads((output / "summary.json").read_bytes())
    assert summary["passed"] is False
    first, second = summary["cases"]
    assert first["technical_expectation_met"] is True
    if problem == "mixed_prompts":
        assert second["technical_expectation_met"] is True
        assert len(summary["prompt_sha256s"]) == 2
    else:
        assert second["technical_expectation_met"] is False
        assert second["problem"] == "unexpected_outcome"


@pytest.mark.parametrize("invalid", ["later_export", "existing_output"])
def test_validates_before_starting_any_case(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    output = tmp_path / "run"
    if invalid == "later_export":
        (dataset.parent / FIXTURES / f"{SKIPPED}.json").write_bytes(b"{}")
    else:
        output.mkdir()
        (output / "summary.json").write_bytes(b"original summary\n")

    calls = install_child(monkeypatch)
    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, dataset, output)

    assert error.value.code == 2
    assert not calls
    if invalid == "later_export":
        assert not output.exists()
    else:
        assert (output / "summary.json").read_bytes() == b"original summary\n"
