import json
import runpy
import sys
from collections.abc import Sequence
from hashlib import sha256
from importlib.util import find_spec
from pathlib import Path
from typing import NoReturn

import pytest

pytestmark = pytest.mark.skipif(
    find_spec("qdrant_client") is None, reason="Requires the retrieval extra"
)
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/evaluate_knowledge.py"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "evals").mkdir()
    (tmp_path / "knowledge/catalog.json").write_text(
        json.dumps({"schema_version": 2, "include_runbooks": False, "documents": []})
    )
    write_dataset(tmp_path, relevant_ids=[])
    return tmp_path


def write_dataset(root: Path, *, relevant_ids: list[str]) -> None:
    (root / "evals/knowledge-retrieval.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cases": [
                    {
                        "id": "heap-checks",
                        "query": "heap",
                        "service": "order-service",
                        "environment": "local",
                        "relevant_document_ids": relevant_ids,
                    }
                ],
            }
        )
    )


def add_document(root: Path, *, approved: bool = False) -> None:
    metadata = {
        "id": "heap-runbook",
        "title": "Heap checks",
        "document_type": "runbook",
        "service": "order-service",
        "environment": "local",
        "owner": "fixture-owner",
        "version": 1,
        "status": "approved" if approved else "draft",
        "reviewed_by": "fixture-reviewer" if approved else None,
        "file": "knowledge/heap.md",
    }
    (root / "knowledge/catalog.json").write_text(
        json.dumps({"schema_version": 2, "include_runbooks": False, "documents": [metadata]})
    )
    (root / "knowledge/heap.md").write_text("Inspect retained heap observations.\n")


def invoke(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *args])
    runpy.run_path(str(SCRIPT), run_name="__main__")


def forbid_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    import openai
    import qdrant_client

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("Validation must finish before external clients are created")

    monkeypatch.setattr(openai, "OpenAI", forbidden)
    monkeypatch.setattr(qdrant_client, "QdrantClient", forbidden)


def test_empty_scopes_need_no_clients_or_key(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    forbid_clients(monkeypatch)
    invoke(monkeypatch, "--root", str(root))
    output = json.loads(capsys.readouterr().out)

    assert output["collection"] is None
    assert output["embedding_total_tokens"] == output["chunk_count"] == 0
    assert output["evaluation"]["mean_recall_at_k"] is None
    assert output["evaluation"]["no_label_cases"] == 1
    assert (
        output["dataset_sha256"]
        == sha256((root / "evals/knowledge-retrieval.json").read_bytes()).hexdigest()
    )


def test_unselected_positive_labels_fail_before_clients(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    add_document(root)
    write_dataset(root, relevant_ids=["heap-runbook"])
    forbid_clients(monkeypatch)

    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, "--root", str(root))

    assert error.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "--include-drafts" in output.err


@pytest.mark.parametrize("k", ["0", "21", "invalid"])
def test_invalid_k_is_a_usage_error(root: Path, k: str, monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_clients(monkeypatch)
    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, "--root", str(root), "--k", k)

    assert error.value.code == 2


@pytest.mark.parametrize("raw", ["{}", "invalid-json", "x" * 1_000_001])
def test_invalid_dataset_fails_before_clients(
    root: Path, raw: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (root / "evals/knowledge-retrieval.json").write_text(raw)
    forbid_clients(monkeypatch)

    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, "--root", str(root))

    assert error.value.code == 1
    assert capsys.readouterr().out == ""


def test_cli_evaluates_existing_local_index_without_rebuilding(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import qdrant_client

    from ai_incident_investigator.knowledge import embeddings
    from ai_incident_investigator.knowledge.corpus import load_knowledge_corpus
    from ai_incident_investigator.knowledge.retrieval_chunks import prepare_corpus_chunks
    from ai_incident_investigator.knowledge.vector_index import QdrantKnowledgeIndex

    class FixtureEmbedder:
        spec = embeddings.EmbeddingSpec(provider="fixture", model="fixture", dimensions=3)
        total_tokens = 0

        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            self.calls.append(tuple(texts))
            return [[1.0, 0.0, 1.0] for _ in texts]

    add_document(root)
    write_dataset(root, relevant_ids=["heap-runbook"])
    chunks = prepare_corpus_chunks(
        load_knowledge_corpus(root, include_drafts=True), include_drafts=True
    )
    connection = qdrant_client.QdrantClient(":memory:")
    embedder = FixtureEmbedder()
    try:
        index = QdrantKnowledgeIndex(connection, embedder)
        collection = index.collection_name(chunks, include_drafts=True)

        with monkeypatch.context() as patch:
            patch.setenv("OPENAI_API_KEY", "fixture-only")
            patch.setattr(qdrant_client, "QdrantClient", lambda **kwargs: connection)
            patch.setattr(connection, "close", lambda: None)
            patch.setattr(embeddings, "OpenAIEmbedder", lambda provider: embedder)

            with pytest.raises(SystemExit) as error:
                invoke(monkeypatch, "--root", str(root), "--include-drafts")

            assert error.value.code == 1
            assert embedder.calls == []
            assert not connection.collection_exists(collection)
            assert capsys.readouterr().out == ""

            index.build(chunks, include_drafts=True)
            embedder.calls.clear()

            invoke(monkeypatch, "--root", str(root), "--include-drafts", "--k", "1")
            output = json.loads(capsys.readouterr().out)

            assert output["collection"] == collection
            assert output["mode"] == "preview"
            assert output["evaluation"]["mean_recall_at_k"] == 1
            assert output["evaluation"]["mean_reciprocal_rank_at_k"] == 1
            assert embedder.calls == [("heap",)]
    finally:
        connection.close()
