import json
import runpy
import sys
from collections.abc import Sequence
from importlib.util import find_spec
from pathlib import Path
from typing import NoReturn

import pytest

pytestmark = pytest.mark.skipif(
    find_spec("qdrant_client") is None, reason="Requires the retrieval extra"
)
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "search_knowledge.py"


@pytest.fixture
def empty_root(tmp_path: Path) -> Path:
    directory = tmp_path / "knowledge"
    directory.mkdir()
    (directory / "catalog.json").write_text(
        json.dumps({"schema_version": 2, "include_runbooks": False, "documents": []})
    )
    return tmp_path


def invoke(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *args])
    runpy.run_path(str(SCRIPT), run_name="__main__")


@pytest.mark.parametrize("command", ["index", "search"])
def test_empty_corpus_needs_no_provider_or_database(
    command: str,
    empty_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import openai
    import qdrant_client

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("Empty corpus must not create external clients")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(openai, "OpenAI", forbidden)
    monkeypatch.setattr(qdrant_client, "QdrantClient", forbidden)
    extra = (
        ("--query", "heap", "--service", "order-service", "--environment", "local")
        if command == "search"
        else ()
    )
    invoke(monkeypatch, command, "--root", str(empty_root), *extra)
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "approved"
    assert result["chunk_count"] == result["embedding_total_tokens"] == 0
    assert result["collection"] is None
    if command == "search":
        assert result["hits"] == []


@pytest.mark.parametrize("limit", ["63", "6001", "invalid"])
def test_invalid_budget_returns_usage_error(
    limit: str, empty_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, "index", "--root", str(empty_root), "--max-characters", limit)
    assert error.value.code == 2


def test_missing_corpus_returns_operation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, "index", "--root", str(tmp_path / "missing"))
    assert error.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "Knowledge operation failed" in output.err


def test_cli_indexes_and_searches_with_real_qdrant_local(
    empty_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import qdrant_client

    from ai_incident_investigator.knowledge import embeddings

    metadata = {
        "id": "cli-example",
        "title": "Heap checks",
        "document_type": "runbook",
        "service": "order-service",
        "environment": "local",
        "owner": "fixture-owner",
        "version": 1,
        "status": "approved",
        "reviewed_by": "fixture-reviewer",
        "file": "knowledge/example.md",
    }
    (empty_root / "knowledge/catalog.json").write_text(
        json.dumps({"schema_version": 2, "include_runbooks": False, "documents": [metadata]})
    )
    (empty_root / "knowledge/example.md").write_text("Inspect heap observations.")

    class FixtureEmbedder:
        spec = embeddings.EmbeddingSpec(provider="fixture", model="fixture", dimensions=3)
        total_tokens = 0

        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            return [[1.0, 0.0, 1.0] for _ in texts]

    connection = qdrant_client.QdrantClient(":memory:")
    try:
        with monkeypatch.context() as patch:
            patch.setenv("OPENAI_API_KEY", "fixture-only")
            patch.setattr(qdrant_client, "QdrantClient", lambda **kwargs: connection)
            patch.setattr(connection, "close", lambda: None)
            patch.setattr(embeddings, "OpenAIEmbedder", lambda provider: FixtureEmbedder())
            invoke(monkeypatch, "index", "--root", str(empty_root))
            indexed = json.loads(capsys.readouterr().out)
            invoke(
                monkeypatch,
                "search",
                "--root",
                str(empty_root),
                "--query",
                "heap",
                "--service",
                "order-service",
                "--environment",
                "local",
            )
            searched = json.loads(capsys.readouterr().out)
            assert indexed["collection"] == searched["collection"]
            assert searched["hits"][0]["chunk"]["document"]["id"] == "cli-example"
            assert searched["embedding_total_tokens"] == 0
    finally:
        connection.close()
