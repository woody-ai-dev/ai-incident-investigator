from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from importlib.util import find_spec
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from ai_incident_investigator.knowledge.documents import KnowledgeMetadata
from ai_incident_investigator.knowledge.embeddings import EmbeddingError, EmbeddingSpec
from ai_incident_investigator.knowledge.extraction import LocalDocumentExtractor
from ai_incident_investigator.knowledge.retrieval_chunks import (
    RetrievalChunk,
    prepare_document_chunks,
)
from ai_incident_investigator.knowledge.vector_index import (
    KnowledgeIndexError,
    QdrantKnowledgeIndex,
    SearchRequest,
)

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

pytestmark = pytest.mark.skipif(
    find_spec("qdrant_client") is None,
    reason="Qdrant checks require the retrieval extra",
)


class FakeEmbedder:
    spec = EmbeddingSpec(
        provider="fixture", model="fixture", dimensions=3, input_version="title-section-v1"
    )

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.vector: list[float] | None = None
        self.fail = False

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(tuple(texts))
        if self.fail:
            raise EmbeddingError("Fixture provider failed")
        return [
            self.vector.copy()
            if self.vector is not None
            else [float("heap" in text.lower()), float("timeout" in text.lower()), 1.0]
            for text in texts
        ]


@pytest.fixture
def client() -> Iterator[QdrantClient]:
    from qdrant_client import QdrantClient

    connection = QdrantClient(":memory:")
    try:
        yield connection
    finally:
        connection.close()


def make_chunks(
    *,
    content: str = "Inspect heap usage and recent service logs.",
    service: str = "order-service",
    environment: str = "local",
    approved: bool = True,
    document_id: str | None = None,
) -> tuple[RetrievalChunk, ...]:
    metadata = KnowledgeMetadata(
        id=document_id or f"test-{uuid4().hex}",
        title="Service checks",
        document_type="runbook",
        service=service,
        environment=environment,
        owner="fixture-owner",
        version=1,
        status="approved" if approved else "draft",
        reviewed_by="fixture-reviewer" if approved else None,
        file="knowledge/example.md",
    )
    document = LocalDocumentExtractor().extract(metadata, content.encode("utf-8"))
    return prepare_document_chunks(document)


def request(**updates: object) -> SearchRequest:
    return SearchRequest.model_validate(
        {"text": "heap checks", "service": "order-service", "environment": "local", **updates}
    )


def test_real_local_search_filters_service_and_environment(client: QdrantClient) -> None:
    matching = make_chunks()
    chunks = (
        *matching,
        *make_chunks(service="payment-service"),
        *make_chunks(environment="production"),
    )
    embedder = FakeEmbedder()
    index = QdrantKnowledgeIndex(client, embedder)
    name = index.build(chunks)

    hits = index.search(chunks, request())

    assert [hit.chunk for hit in hits] == list(matching)
    assert -1.000001 <= hits[0].score <= 1.000001
    records, _ = client.scroll(name, limit=20, with_payload=True, with_vectors=False)
    assert len(records) == 3
    assert {record.payload["chunk_id"] for record in records if record.payload} == {
        chunk.id for chunk in chunks
    }
    assert all(str(UUID(str(record.id))) == str(record.id) for record in records)


def test_complete_collection_is_reused_without_another_embedding_call(client: QdrantClient) -> None:
    chunks = make_chunks()
    embedder = FakeEmbedder()
    index = QdrantKnowledgeIndex(client, embedder)

    first = index.build(chunks)
    calls = len(embedder.calls)

    assert index.build(tuple(reversed(chunks))) == first
    assert len(embedder.calls) == calls
    embedder.spec = embedder.spec.model_copy(update={"model": "different-model"})
    with pytest.raises(KnowledgeIndexError):
        index.search(chunks, request())
    assert len(embedder.calls) == calls


def test_changed_corpus_cannot_query_previous_snapshot(client: QdrantClient) -> None:
    previous = make_chunks(document_id="stable-document")
    current = make_chunks(document_id="stable-document", content="Inspect timeout reports.")
    embedder = FakeEmbedder()
    index = QdrantKnowledgeIndex(client, embedder)
    index.build(previous)
    calls = len(embedder.calls)

    with pytest.raises(KnowledgeIndexError):
        index.search(current, request())

    assert len(embedder.calls) == calls
    assert index.search(previous, request())[0].chunk == previous[0]


def test_removing_one_document_requires_a_new_snapshot(client: QdrantClient) -> None:
    remaining = make_chunks()
    index = QdrantKnowledgeIndex(client, FakeEmbedder())
    index.build((*remaining, *make_chunks()))

    with pytest.raises(KnowledgeIndexError):
        index.search(remaining, request())


def test_empty_current_corpus_ignores_old_points_without_model_calls(client: QdrantClient) -> None:
    embedder = FakeEmbedder()
    index = QdrantKnowledgeIndex(client, embedder)
    index.build(make_chunks())
    calls = len(embedder.calls)

    assert index.search((), request()) == ()
    index.build(())
    assert len(embedder.calls) == calls


def test_preview_collection_does_not_supply_missing_approved_index(client: QdrantClient) -> None:
    chunks = make_chunks()
    index = QdrantKnowledgeIndex(client, FakeEmbedder())
    preview = index.build(chunks, include_drafts=True)

    with pytest.raises(KnowledgeIndexError):
        index.search(chunks, request())

    assert index.search(chunks, request(), include_drafts=True)[0].chunk == chunks[0]
    assert index.build(chunks) != preview


def test_approved_entry_points_reject_drafts_and_duplicate_ids(client: QdrantClient) -> None:
    draft = make_chunks(approved=False)
    index = QdrantKnowledgeIndex(client, FakeEmbedder())
    for operation in (index.build, lambda chunks: index.search(chunks, request())):
        with pytest.raises(KnowledgeIndexError):
            operation(draft)
        with pytest.raises(KnowledgeIndexError):
            operation((*draft, *draft))

    index.build(draft, include_drafts=True)
    assert index.search(draft, request(), include_drafts=True)[0].chunk.document.status == "draft"


def test_incomplete_collection_is_unsearchable_and_can_be_rebuilt(client: QdrantClient) -> None:
    from qdrant_client import models

    chunks = make_chunks()
    index = QdrantKnowledgeIndex(client, FakeEmbedder())
    name = index.build(chunks)
    records, _ = client.scroll(name)
    client.delete(name, points_selector=models.PointIdsList(points=[records[0].id]), wait=True)

    with pytest.raises(KnowledgeIndexError):
        index.search(chunks, request())

    assert index.build(chunks) == name
    assert index.search(chunks, request())[0].chunk == chunks[0]


@pytest.mark.parametrize("vector", [[1.0, 2.0], [float("nan"), 0.0, 1.0], [float("inf"), 0.0, 1.0]])
def test_invalid_vectors_never_create_a_searchable_snapshot(
    client: QdrantClient, vector: list[float]
) -> None:
    chunks = make_chunks()
    embedder = FakeEmbedder()
    embedder.vector = vector
    index = QdrantKnowledgeIndex(client, embedder)

    with pytest.raises((EmbeddingError, KnowledgeIndexError)):
        index.build(chunks)
    with pytest.raises(KnowledgeIndexError):
        index.search(chunks, request())


def test_provider_failure_preserves_previous_snapshot(client: QdrantClient) -> None:
    previous = make_chunks(document_id="stable-document")
    current = make_chunks(document_id="stable-document", content="Inspect timeout reports.")
    embedder = FakeEmbedder()
    index = QdrantKnowledgeIndex(client, embedder)
    index.build(previous)
    embedder.fail = True

    with pytest.raises((EmbeddingError, KnowledgeIndexError)):
        index.build(current)
    with pytest.raises(KnowledgeIndexError):
        index.search(current, request())

    embedder.fail = False
    assert index.search(previous, request())[0].chunk == previous[0]


@pytest.mark.qdrant_server
def test_same_index_contract_with_real_qdrant_server() -> None:
    from qdrant_client import QdrantClient

    url = os.getenv("TEST_QDRANT_URL")
    if not url:
        pytest.skip("TEST_QDRANT_URL is required for the Qdrant server check")
    connection = QdrantClient(url=url, timeout=10)
    name: str | None = None
    try:
        chunks = make_chunks()
        index = QdrantKnowledgeIndex(connection, FakeEmbedder())
        name = index.build(chunks)
        assert index.search(chunks, request())[0].chunk == chunks[0]
    finally:
        if name is not None:
            connection.delete_collection(name)
        connection.close()
