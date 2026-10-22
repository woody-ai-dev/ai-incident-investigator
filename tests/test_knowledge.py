import json
from hashlib import sha256
from pathlib import Path
from typing import Literal

import pytest
from pydantic import Field

from ai_incident_investigator.knowledge.loader import (
    MAX_RUNBOOK_BYTES,
    CorpusError,
    approved_runbooks,
    load_corpus,
)
from ai_incident_investigator.knowledge.models import (
    Identifier,
    KnowledgeModel,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_corpus(
    root: Path,
    *,
    content: bytes = b"# Payment timeout\n\nInspect matching logs.\n",
    **overrides: object,
) -> Path:
    metadata: dict[str, object] = {
        "id": "payment-timeout",
        "title": "Investigate a payment timeout",
        "service": "order-service",
        "environment": "local",
        "owner": "test-owner",
        "version": 1,
        "status": "draft",
        "reviewed_by": None,
        "file": "payment-timeout.md",
    }
    metadata.update(overrides)

    catalog = {
        "schema_version": 1,
        "documents": [metadata],
    }

    (root / "catalog.json").write_text(
        json.dumps(catalog),
        encoding="utf-8",
    )
    (root / "payment-timeout.md").write_bytes(content)

    return root


def test_loads_document_and_hashes_exact_file_bytes(tmp_path: Path) -> None:
    content = b"# Payment timeout\r\n\r\nInspect matching logs.\r\n"
    write_corpus(tmp_path, content=content)

    documents = load_corpus(tmp_path)

    assert len(documents) == 1
    assert documents[0].metadata.id == "payment-timeout"
    assert documents[0].content == content.decode("utf-8")
    assert documents[0].content_sha256 == sha256(content).hexdigest()


def test_content_change_changes_hash(tmp_path: Path) -> None:
    write_corpus(tmp_path)
    before = load_corpus(tmp_path)[0]

    (tmp_path / "payment-timeout.md").write_text(
        "# Payment timeout\n\nInspect logs and request identifiers.\n",
        encoding="utf-8",
    )
    after = load_corpus(tmp_path)[0]

    assert before.metadata.id == after.metadata.id
    assert before.content_sha256 != after.content_sha256


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "../payment-timeout"},
        {"file": "../payment-timeout.md"},
        {"title": "   "},
        {"owner": ""},
        {"version": 0},
        {"version": "1"},
        {"version": True},
        {"status": "published"},
        {"status": "approved", "reviewed_by": None},
        {"status": "approved", "reviewed_by": "   "},
        {"status": "draft", "reviewed_by": "reviewer"},
        {"unexpected": "value"},
    ],
)
def test_rejects_invalid_metadata(
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    write_corpus(tmp_path)
    path = tmp_path / "catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    catalog["documents"][0].update(overrides)
    path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(CorpusError, match="Invalid runbook catalog"):
        load_corpus(tmp_path)


@pytest.mark.parametrize("field", ["owner", "service", "environment", "status", "version"])
def test_rejects_missing_required_metadata(
    tmp_path: Path,
    field: str,
) -> None:
    write_corpus(tmp_path)
    path = tmp_path / "catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    del catalog["documents"][0][field]
    path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(CorpusError, match="Invalid runbook catalog"):
        load_corpus(tmp_path)


@pytest.mark.parametrize("duplicate", ["id", "file"])
def test_rejects_duplicate_documents(tmp_path: Path, duplicate: str) -> None:
    write_corpus(tmp_path)
    path = tmp_path / "catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    original = catalog["documents"][0]

    second = {
        **original,
        "id": "another-runbook",
        "file": "another-runbook.md",
    }
    second[duplicate] = original[duplicate]
    catalog["documents"].append(second)
    path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(CorpusError, match="Invalid runbook catalog"):
        load_corpus(tmp_path)


def test_rejects_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "catalog.json").write_text("{", encoding="utf-8")

    with pytest.raises(CorpusError, match="Invalid runbook catalog"):
        load_corpus(tmp_path)


def test_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="directory does not exist"):
        load_corpus(tmp_path / "missing")


def test_rejects_missing_catalog(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="Cannot read corpus file"):
        load_corpus(tmp_path)


def test_rejects_missing_document(tmp_path: Path) -> None:
    write_corpus(tmp_path)
    (tmp_path / "payment-timeout.md").unlink()

    with pytest.raises(CorpusError, match="Cannot read corpus file"):
        load_corpus(tmp_path)


@pytest.mark.parametrize("content", [b"", b" \n\t", b"\xff"])
def test_rejects_invalid_document_content(
    tmp_path: Path,
    content: bytes,
) -> None:
    write_corpus(tmp_path, content=content)

    with pytest.raises(CorpusError):
        load_corpus(tmp_path)


def test_rejects_oversized_document(tmp_path: Path) -> None:
    write_corpus(
        tmp_path,
        content=b"x" * (MAX_RUNBOOK_BYTES + 1),
    )

    with pytest.raises(CorpusError, match="too large"):
        load_corpus(tmp_path)


@pytest.mark.parametrize("filename", ["catalog.json", "payment-timeout.md"])
def test_rejects_symbolic_links(tmp_path: Path, filename: str) -> None:
    write_corpus(tmp_path)
    path = tmp_path / filename
    target = tmp_path / f"{filename}.target"
    path.rename(target)
    path.symlink_to(target)

    with pytest.raises(CorpusError, match="symbolic link"):
        load_corpus(tmp_path)


def test_draft_documents_are_not_eligible(tmp_path: Path) -> None:
    write_corpus(tmp_path)

    selected = approved_runbooks(
        load_corpus(tmp_path),
        service="order-service",
        environment="local",
    )

    assert selected == ()


@pytest.mark.parametrize(
    ("service", "environment", "expected_count"),
    [
        ("order-service", "local", 1),
        ("inventory-service", "local", 0),
        ("order-service", "production", 0),
    ],
)
def test_approved_documents_require_exact_scope(
    tmp_path: Path,
    service: str,
    environment: str,
    expected_count: int,
) -> None:
    write_corpus(
        tmp_path,
        status="approved",
        reviewed_by="test-reviewer",
    )

    selected = approved_runbooks(
        load_corpus(tmp_path),
        service=service,
        environment=environment,
    )

    assert len(selected) == expected_count


def test_documents_are_returned_in_stable_id_order(tmp_path: Path) -> None:
    write_corpus(tmp_path)
    path = tmp_path / "catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    original = catalog["documents"][0]

    catalog["documents"].append(
        {
            **original,
            "id": "aaa-runbook",
            "file": "aaa-runbook.md",
        }
    )
    path.write_text(json.dumps(catalog), encoding="utf-8")
    (tmp_path / "aaa-runbook.md").write_text(
        "# Another runbook\n",
        encoding="utf-8",
    )

    documents = load_corpus(tmp_path)

    assert [document.metadata.id for document in documents] == [
        "aaa-runbook",
        "payment-timeout",
    ]


class RetrievalCase(KnowledgeModel):
    id: Identifier
    query: str = Field(min_length=1, max_length=1000)
    service: Identifier
    environment: Identifier
    relevant_document_ids: tuple[Identifier, ...]


class RetrievalDataset(KnowledgeModel):
    schema_version: Literal[1]
    cases: tuple[RetrievalCase, ...] = Field(min_length=1)


def test_repository_corpus_and_retrieval_labels_are_consistent() -> None:
    documents = load_corpus(PROJECT_ROOT / "runbooks")
    by_id = {document.metadata.id: document for document in documents}
    dataset = RetrievalDataset.model_validate_json(
        (PROJECT_ROOT / "evals" / "knowledge-retrieval.json").read_bytes()
    )

    assert set(by_id) == {
        "payment-timeout",
        "heap-investigation",
        "partial-collection",
    }

    case_ids = [case.id for case in dataset.cases]
    assert len(case_ids) == len(set(case_ids))
    assert any(not case.relevant_document_ids for case in dataset.cases)

    for case in dataset.cases:
        relevant_ids = case.relevant_document_ids
        assert len(relevant_ids) == len(set(relevant_ids))

        for document_id in relevant_ids:
            assert document_id in by_id
            metadata = by_id[document_id].metadata
            assert metadata.service == case.service
            assert metadata.environment == case.environment


@pytest.mark.parametrize("content", [b"  # Title\n\nBody.\n\n", b"# Title\r\n\r\nBody.\r\n"])
def test_preserves_markdown_whitespace(tmp_path: Path, content: bytes) -> None:
    write_corpus(tmp_path, content=content)

    document = load_corpus(tmp_path)[0]

    assert document.content.encode("utf-8") == content
    assert document.content_sha256 == sha256(content).hexdigest()
