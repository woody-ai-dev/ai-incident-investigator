import json
import runpy
import sys
from collections.abc import Sequence
from importlib.util import find_spec
from pathlib import Path
from typing import NoReturn

import httpx2 as httpx
import pytest
from openai import OpenAI

pytestmark = pytest.mark.skipif(
    find_spec("qdrant_client") is None, reason="Requires the retrieval extra"
)
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/recommend_knowledge.py"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "knowledge").mkdir()
    metadata = {
        "id": "heap-checks",
        "title": "Heap checks",
        "document_type": "runbook",
        "file": "knowledge/heap.md",
        "service": "order-service",
        "environment": "local",
        "owner": "fixture-owner",
        "version": 1,
        "status": "draft",
        "reviewed_by": None,
    }
    (tmp_path / "knowledge/catalog.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "include_runbooks": False,
                "documents": [metadata],
            }
        )
    )
    (tmp_path / "knowledge/heap.md").write_text("Inspect retained heap and GC records.\n")
    (tmp_path / "incident.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "request": {
                    "service": "order-service",
                    "environment": "local",
                    "start_time": "2026-10-17T10:00:00Z",
                    "end_time": "2026-10-17T10:05:00Z",
                },
                "report": {
                    "summary": "OLD_GENERATED_SUMMARY",
                    "findings": [],
                    "hypotheses": [],
                    "recommended_checks": [],
                    "missing_data": [],
                    "evidence": [
                        {
                            "id": "log-1",
                            "source": "log",
                            "service": "order-service",
                            "summary": "A simulated timeout was recorded.",
                            "reference": "fixture:line:1",
                            "start_time": "2026-10-17T10:01:00Z",
                        }
                    ],
                },
            }
        )
    )
    return tmp_path


def invoke(monkeypatch: pytest.MonkeyPatch, root: Path, *extra: str) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--root",
            str(root),
            "--investigation",
            str(root / "incident.json"),
            "--query",
            "heap",
            "--model",
            "test-model",
            *extra,
        ],
    )
    runpy.run_path(str(SCRIPT), run_name="__main__")


def test_draft_only_corpus_is_skipped_without_external_clients(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import openai
    import qdrant_client

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("No approved context must create no external clients")

    monkeypatch.setattr(openai, "OpenAI", forbidden)
    monkeypatch.setattr(qdrant_client, "QdrantClient", forbidden)
    original = (root / "incident.json").read_bytes()
    invoke(monkeypatch, root)
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "skipped"
    assert output["embedding_total_tokens"] == 0
    assert output["generation_usage"] is None
    assert output["assembly"]["context"]["chunks"] == []
    assert (root / "incident.json").read_bytes() == original


def test_namespace_collision_is_rejected_before_clients(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import openai

    from ai_incident_investigator.knowledge.corpus import load_knowledge_corpus
    from ai_incident_investigator.knowledge.retrieval_chunks import prepare_corpus_chunks

    chunks = prepare_corpus_chunks(
        load_knowledge_corpus(root, include_drafts=True), include_drafts=True
    )
    path = root / "incident.json"
    data = json.loads(path.read_text())
    data["report"]["evidence"][0]["id"] = chunks[0].id
    path.write_text(json.dumps(data))

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("Ambiguous references must be rejected before clients")

    monkeypatch.setattr(openai, "OpenAI", forbidden)
    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, root, "--include-drafts")
    assert error.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "overlap" in output.err


@pytest.mark.parametrize(
    "mode",
    [
        "completed",
        "incomplete",
        "unknown-reference",
        "missing-index",
        "embedding-error",
        "no-context",
        "inapplicable",
        "qdrant-error",
    ],
)
def test_cli_runs_retrieval_assembly_and_generation_with_recorded_failures(
    root: Path, mode: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import openai
    import qdrant_client
    from qdrant_client.http.exceptions import ResponseHandlingException

    from ai_incident_investigator.knowledge import embeddings
    from ai_incident_investigator.knowledge.corpus import load_knowledge_corpus
    from ai_incident_investigator.knowledge.embeddings import EmbeddingError, EmbeddingSpec
    from ai_incident_investigator.knowledge.retrieval_chunks import prepare_corpus_chunks
    from ai_incident_investigator.knowledge.vector_index import QdrantKnowledgeIndex

    class FixtureEmbedder:
        spec = EmbeddingSpec(provider="fixture", model="fixture", dimensions=3)

        def __init__(self, *, fail: bool = False) -> None:
            self.total_tokens = 0
            self.fail = fail

        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            if self.fail:
                raise EmbeddingError("Fixture embedding failure")
            self.total_tokens += len(texts) * 3
            return [[1.0, 0.0, 1.0] for _ in texts]

    if mode == "inapplicable":
        catalog_path = root / "knowledge/catalog.json"
        catalog = json.loads(catalog_path.read_text())
        catalog["documents"][0]["applicability"] = [
            {"kind": "log_prefix", "prefix": "JVM garbage collection stalled:"}
        ]
        catalog_path.write_text(json.dumps(catalog))

    chunks = prepare_corpus_chunks(
        load_knowledge_corpus(root, include_drafts=True), include_drafts=True
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert "OLD_GENERATED_SUMMARY" not in request.content.decode()
        payload = json.loads(json.loads(request.content)["input"][0]["content"])
        assert payload["knowledge_context"]["mode"] == "preview"
        knowledge_id = "chunk-" + "f" * 64 if mode == "unknown-reference" else chunks[0].id
        answer = {
            "checks": [
                {
                    "action": "Inspect retained GC records.",
                    "reason": "Memory cause is unconfirmed.",
                    "evidence_ids": ["log-1"],
                    "knowledge_ids": [knowledge_id],
                }
            ],
            "limitations": [],
        }
        return httpx.Response(
            200,
            json={
                "id": "resp_fixture",
                "object": "response",
                "created_at": 1,
                "model": "test-model",
                "status": "incomplete" if mode == "incomplete" else "completed",
                "usage": {
                    "input_tokens": 10,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
                "output": [
                    {
                        "id": "msg_fixture",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": json.dumps(answer), "annotations": []}
                        ],
                    }
                ],
            },
        )

    def provider(**kwargs: object) -> OpenAI:
        assert kwargs["base_url"] == "https://api.openai.com/v1"
        return OpenAI(
            api_key="fixture",
            base_url="https://example.invalid/v1",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    connection = qdrant_client.QdrantClient(":memory:")
    try:
        if mode != "missing-index":
            QdrantKnowledgeIndex(connection, FixtureEmbedder()).build(chunks, include_drafts=True)
        with monkeypatch.context() as patch:
            patch.setenv("OPENAI_API_KEY", "fixture")
            patch.setenv("OPENAI_BASE_URL", "https://untrusted.invalid")
            patch.setattr(openai, "OpenAI", provider)
            patch.setattr(qdrant_client, "QdrantClient", lambda **kwargs: connection)
            close_calls = 0

            def record_close() -> None:
                nonlocal close_calls
                close_calls += 1

            patch.setattr(connection, "close", record_close)
            if mode == "qdrant-error":

                def query_failure(*args: object, **kwargs: object) -> NoReturn:
                    raise ResponseHandlingException(RuntimeError("Fixture Qdrant failure"))

                patch.setattr(connection, "query_points", query_failure)
            patch.setattr(
                embeddings,
                "OpenAIEmbedder",
                lambda provider: FixtureEmbedder(fail=mode == "embedding-error"),
            )
            extra = (
                ("--include-drafts", "--context-max-bytes", "512")
                if mode == "no-context"
                else ("--include-drafts",)
            )
            if mode in {"completed", "no-context", "inapplicable"}:
                invoke(monkeypatch, root, *extra)
            else:
                with pytest.raises(SystemExit) as error:
                    invoke(monkeypatch, root, *extra)
                assert error.value.code == 1
            output = json.loads(capsys.readouterr().out)
            assert close_calls == 1
        expected = {
            "completed": "completed",
            "no-context": "skipped",
            "inapplicable": "skipped",
        }.get(mode, "failed")
        assert output["status"] == expected
        assert output["mode"] == "preview"
        assert calls == int(mode in {"completed", "incomplete", "unknown-reference"})
        if mode == "completed":
            assert output["recommendations"]["checks"][0]["knowledge_ids"] == [chunks[0].id]
            assert output["recommendations"]["limitations"] == [
                "This is a preview that may use unreviewed guidance."
            ]
        elif mode != "no-context":
            assert output["recommendations"] is None
        if mode in {"completed", "incomplete", "unknown-reference"}:
            assert output["generation_usage"]["tokens"]["total_tokens"] == 15
        if mode == "inapplicable":
            assert output["issue"] == (
                "No retrieved knowledge documents match the recorded observations."
            )
            assert output["collection"] == QdrantKnowledgeIndex(
                connection, FixtureEmbedder()
            ).collection_name(chunks, include_drafts=True)
            assert output["generation_usage"] is None
            assert output["assembly"]["context"]["chunks"] == []
            assert output["assembly"]["omitted"] == [
                {"chunk_id": chunks[0].id, "reason": "inapplicable"}
            ]
        if mode == "qdrant-error":
            assert output["generation_usage"] is None
            assert output["issue"] == "Qdrant request failed; check the service and credentials"
        if mode == "embedding-error":
            assert output["embedding_total_tokens"] is None
        elif mode == "missing-index":
            assert output["embedding_total_tokens"] == 0
        else:
            assert output["embedding_total_tokens"] == 3
    finally:
        connection.close()


def test_scope_without_documents_is_skipped_without_clients(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import openai
    import qdrant_client

    path = root / "incident.json"
    data = json.loads(path.read_text())
    data["request"]["environment"] = "production"
    path.write_text(json.dumps(data))

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("An empty scope must create no external clients")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(openai, "OpenAI", forbidden)
    monkeypatch.setattr(qdrant_client, "QdrantClient", forbidden)
    invoke(monkeypatch, root, "--include-drafts")
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "skipped"
    assert output["collection"] is None
    assert output["embedding_total_tokens"] == 0
    assert output["generation_usage"] is None
    assert output["assembly"]["context"]["environment"] == "production"
    assert output["assembly"]["context"]["chunks"] == []


def test_oversized_observations_fail_before_clients(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import openai
    import qdrant_client

    path = root / "incident.json"
    data = json.loads(path.read_text())
    evidence = data["report"]["evidence"][0]
    data["report"]["evidence"] = [
        {**evidence, "id": f"log-{number}", "summary": "x" * 4000} for number in range(10)
    ]
    path.write_text(json.dumps(data))

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("Oversized observations must be rejected before clients")

    monkeypatch.setattr(openai, "OpenAI", forbidden)
    monkeypatch.setattr(qdrant_client, "QdrantClient", forbidden)
    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, root, "--include-drafts")
    assert error.value.code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "failed"
    assert "size limit" in output["issue"]
    assert output["embedding_total_tokens"] == 0
    assert output["generation_usage"] is None


@pytest.mark.parametrize("url", ["ftp://example.invalid:1234", "http://[invalid"])
def test_invalid_qdrant_configuration_is_a_usage_error(
    root: Path,
    url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import openai

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("Invalid Qdrant configuration must not create an OpenAI client")

    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setattr(openai, "OpenAI", forbidden)
    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, root, "--include-drafts", "--qdrant-url", url)
    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "Invalid Qdrant URL or client configuration" in output.err
