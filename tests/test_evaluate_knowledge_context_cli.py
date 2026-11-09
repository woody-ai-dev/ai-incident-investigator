import json
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from ai_incident_investigator.knowledge.embeddings import EmbeddingSpec
from ai_incident_investigator.knowledge.extraction import LocalDocumentExtractor
from ai_incident_investigator.knowledge.retrieval_chunks import (
    RetrievalChunk,
    prepare_document_chunks,
)
from ai_incident_investigator.knowledge.vector_index import knowledge_collection_name
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


def invoke(monkeypatch: pytest.MonkeyPatch, dataset: Path, artifact: Path, *extra: str) -> None:
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
            *extra,
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


@pytest.fixture
def prepared_case(case_files: tuple[Path, Path], tmp_path: Path) -> tuple[Path, Path, Path]:
    dataset, artifact = case_files
    data = json.loads(artifact.read_bytes())
    selected = RetrievalChunk.model_validate(data["assembly"]["context"]["chunks"][0]["chunk"])
    extractor = LocalDocumentExtractor()
    extra_chunks = []
    for document_id, text in (
        ("heap-limits", b"Inspect retained heap limits.\n"),
        ("heap-baseline", b"Compare with a retained heap baseline.\n"),
    ):
        metadata = selected.document.model_copy(
            update={"id": document_id, "file": f"knowledge/{document_id}.md"}
        )
        (chunk,) = prepare_document_chunks(
            extractor.extract(metadata, text), policy=selected.policy
        )
        extra_chunks.append(chunk)
    omitted, missed = extra_chunks
    chunks = selected, omitted, missed
    data["collection"] = knowledge_collection_name(
        chunks, EmbeddingSpec.model_validate(data["embedding"])
    )
    data["assembly"]["policy"]["max_chunks"] = 1
    data["assembly"]["omitted"] = [
        {"chunk_id": omitted.id, "reason": "chunk_limit"},
        {"chunk_id": omitted.id, "reason": "duplicate"},
    ]
    artifact.write_text(json.dumps(data), encoding="utf-8")

    labels = json.loads(dataset.read_bytes())
    passages = labels["cases"][0]["expected_context"]
    passages[0].update(document_id=omitted.document.id, section=omitted.section)
    passages.extend(
        [
            {
                "document_id": missed.document.id,
                "section": missed.section,
                "text_contains": "retained heap baseline",
            },
            {
                "document_id": selected.document.id,
                "section": selected.section,
                "text_contains": "retained thread dumps",
            },
        ]
    )
    dataset.write_text(json.dumps(labels), encoding="utf-8")

    prepared = tmp_path / "prepared.json"
    prepared.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": data["mode"],
                "policy": selected.policy.model_dump(mode="json"),
                "document_count": len(chunks),
                "chunk_count": len(chunks),
                "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            }
        ),
        encoding="utf-8",
    )
    return dataset, artifact, prepared


def test_prepared_chunks_identify_where_passages_were_lost(
    prepared_case: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset, artifact, prepared = prepared_case
    invoke(monkeypatch, dataset, artifact, "--prepared-chunks", str(prepared))

    result = json.loads(capsys.readouterr().out)
    selected, omitted, missed = json.loads(prepared.read_bytes())["chunks"]
    assert result["prepared_chunks_sha256"] == sha256(prepared.read_bytes()).hexdigest()
    assert result["passage_coverage"] == 0.25
    assert [passage["retrieval_diagnosis"] for passage in result["passages"]] == [
        {
            "status": "omitted_by_budget",
            "eligible_chunk_ids": [omitted["id"]],
            "omitted": [{"chunk_id": omitted["id"], "reason": "chunk_limit"}],
        },
        {"status": "selected", "eligible_chunk_ids": [selected["id"]], "omitted": []},
        {"status": "not_retrieved", "eligible_chunk_ids": [missed["id"]], "omitted": []},
        {"status": "not_in_scoped_snapshot", "eligible_chunk_ids": [], "omitted": []},
    ]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("remove_chunk", "collection"),
        ("edit_content", "Prepared chunk IDs must match their content and provenance"),
    ],
)
def test_prepared_chunks_reject_a_different_snapshot(
    prepared_case: tuple[Path, Path, Path],
    change: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset, artifact, prepared = prepared_case
    snapshot = json.loads(prepared.read_bytes())
    if change == "remove_chunk":
        snapshot["chunks"].pop()
        snapshot["chunk_count"] -= 1
        snapshot["document_count"] -= 1
    else:
        chunk = snapshot["chunks"][-1]
        chunk["content"] = "X" + chunk["content"][1:]
    prepared.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, dataset, artifact, "--prepared-chunks", str(prepared))
    output = capsys.readouterr()
    assert error.value.code == 2
    assert output.out == ""
    assert message in output.err
