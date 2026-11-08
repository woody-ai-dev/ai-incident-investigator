import json
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from scripts import evaluate_knowledge_context as cli

FIXTURE = Path(__file__).parent / "fixtures" / "knowledge" / "recommendations.json"


@pytest.fixture
def case_files(tmp_path: Path) -> tuple[Path, Path]:
    data = json.loads(FIXTURE.read_bytes())
    export = tmp_path / "fixtures" / "knowledge-recommendations" / "heap.json"
    export.parent.mkdir(parents=True)
    export_bytes = json.dumps(data["investigation"]).encode("utf-8")
    export.write_bytes(export_bytes)
    data["input_sha256"] = sha256(export_bytes).hexdigest()
    data["assembly"]["omitted"] = [{"chunk_id": "chunk-" + "f" * 64, "reason": "byte_budget"}]

    artifact = tmp_path / "artifact.json"
    artifact.write_text(json.dumps(data), encoding="utf-8")
    label = {"document_id": "heap-review-fixture", "section": "Historical heap checks"}
    case = {
        "id": "heap",
        "query": data["query"],
        "expected_status": "completed",
        "expected_context": [
            {**label, "text_contains": "retained heap limits"},
            {**label, "text_contains": "GC/OOM\nrecords"},
        ],
        "review_questions": [],
    }
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"schema_version": 1, "cases": [case]}), encoding="utf-8")
    return dataset, artifact


def invoke(monkeypatch: pytest.MonkeyPatch, dataset: Path, artifact: Path) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_knowledge_context.py",
            "--case",
            "heap",
            "--dataset",
            str(dataset),
            "--artifact",
            str(artifact),
        ],
    )
    cli.main()


def test_context_coverage_uses_selected_passages(
    case_files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset, artifact = case_files
    invoke(monkeypatch, dataset, artifact)

    result = json.loads(capsys.readouterr().out)
    data = json.loads(artifact.read_bytes())
    assert result["passage_coverage"] == 0.5
    assert result["technical_expectation_met"] is True
    assert result["passages"][0]["selected_chunk_ids"] == []
    assert result["passages"][1]["selected_chunk_ids"] == [
        data["assembly"]["context"]["chunks"][0]["chunk"]["id"]
    ]
    assert result["omitted"] == data["assembly"]["omitted"]


@pytest.mark.parametrize("field", ["input_sha256", "query"])
def test_context_rejects_another_export_or_query(
    case_files: tuple[Path, Path],
    field: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset, artifact = case_files
    data = json.loads(artifact.read_bytes())
    data[field] = "f" * 64 if field == "input_sha256" else "another query"
    artifact.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, dataset, artifact)
    output = capsys.readouterr()
    assert error.value.code == 2
    assert output.out == ""
    assert "does not match the case export/query" in output.err


def test_failure_without_observed_context_is_unscored(
    case_files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset, artifact = case_files
    data = json.loads(artifact.read_bytes())
    data.update(
        status="failed",
        issue="Embedding failed",
        assembly=None,
        recommendations=None,
        generation_usage=None,
    )
    artifact.write_text(json.dumps(data), encoding="utf-8")

    invoke(monkeypatch, dataset, artifact)

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed"
    assert result["technical_expectation_met"] is False
    assert result["passage_coverage"] is None
    assert result["passages"][0]["selected_chunk_ids"] is None
