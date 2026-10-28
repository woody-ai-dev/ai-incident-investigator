import json
import math
from hashlib import sha256
from typing import TYPE_CHECKING, Annotated
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field

from ai_incident_investigator.knowledge.embeddings import (
    Embedder,
    embedding_text,
    validate_vectors,
)
from ai_incident_investigator.knowledge.models import Identifier, KnowledgeModel
from ai_incident_investigator.knowledge.retrieval_chunks import RetrievalChunk

if TYPE_CHECKING:
    from qdrant_client import QdrantClient


class KnowledgeIndexError(ValueError):
    """The current knowledge snapshot is unavailable or inconsistent."""


class SearchRequest(KnowledgeModel):
    text: str = Field(min_length=1, max_length=4000)
    service: Identifier
    environment: Identifier
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 5


class SearchHit(KnowledgeModel):
    chunk: RetrievalChunk
    score: float = Field(allow_inf_nan=False)


def _point_id(chunk_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"ai-incident-investigator:{chunk_id}"))


class QdrantKnowledgeIndex:
    def __init__(self, client: "QdrantClient", embedder: Embedder) -> None:
        self._client = client
        self._embedder = embedder

    def collection_name(
        self, chunks: tuple[RetrievalChunk, ...], *, include_drafts: bool = False
    ) -> str:
        ids = [chunk.id for chunk in chunks]
        if len(ids) != len(set(ids)):
            raise KnowledgeIndexError("Chunk IDs must be unique")
        if not include_drafts and any(chunk.document.status != "approved" for chunk in chunks):
            raise KnowledgeIndexError("Approved index cannot contain draft documents")
        identity = json.dumps(
            {
                "version": "qdrant-snapshot-v1",
                "embedding": self._embedder.spec.fingerprint,
                "chunks": sorted(ids),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        mode = "preview" if include_drafts else "approved"
        return f"knowledge_{mode}_{sha256(identity).hexdigest()[:32]}"

    def _check_config(self, collection: str) -> None:
        from qdrant_client import models

        vectors = self._client.get_collection(collection).config.params.vectors
        if (
            not isinstance(vectors, models.VectorParams)
            or vectors.size != self._embedder.spec.dimensions
            or vectors.distance != models.Distance.COSINE
        ):
            raise KnowledgeIndexError("Index embedding configuration does not match")

    def build(self, chunks: tuple[RetrievalChunk, ...], *, include_drafts: bool = False) -> str:
        from qdrant_client import models

        collection = self.collection_name(chunks, include_drafts=include_drafts)
        if not chunks:
            return collection
        if self._client.collection_exists(collection):
            self._check_config(collection)
            if self._client.count(collection, exact=True).count == len(chunks):
                return collection
        else:
            self._client.create_collection(
                collection,
                vectors_config=models.VectorParams(
                    size=self._embedder.spec.dimensions, distance=models.Distance.COSINE
                ),
            )

        mode = "preview" if include_drafts else "approved"
        for start in range(0, len(chunks), 64):
            batch = chunks[start : start + 64]
            vectors = self._embedder.embed([embedding_text(chunk) for chunk in batch])
            validate_vectors(vectors, count=len(batch), dimensions=self._embedder.spec.dimensions)
            points = [
                models.PointStruct(
                    id=_point_id(chunk.id),
                    vector=vector,
                    payload={
                        "chunk_id": chunk.id,
                        "service": chunk.document.service,
                        "environment": chunk.document.environment,
                        "status": chunk.document.status,
                        "mode": mode,
                        "embedding": self._embedder.spec.fingerprint,
                    },
                )
                for chunk, vector in zip(batch, vectors, strict=True)
            ]
            self._client.upsert(collection, points, wait=True)
        if self._client.count(collection, exact=True).count != len(chunks):
            raise KnowledgeIndexError("Index build is incomplete")
        return collection

    def search(
        self,
        chunks: tuple[RetrievalChunk, ...],
        request: SearchRequest,
        *,
        include_drafts: bool = False,
    ) -> tuple[SearchHit, ...]:
        from qdrant_client import models

        collection = self.collection_name(chunks, include_drafts=include_drafts)
        eligible = {
            chunk.id: chunk
            for chunk in chunks
            if chunk.document.service == request.service
            and chunk.document.environment == request.environment
        }
        if not eligible:
            return ()
        if not self._client.collection_exists(collection):
            raise KnowledgeIndexError("Current corpus is not indexed; run the index command")
        self._check_config(collection)
        if self._client.count(collection, exact=True).count != len(chunks):
            raise KnowledgeIndexError("Current index is incomplete; run the index command")

        vectors = self._embedder.embed([request.text])
        validate_vectors(vectors, count=1, dimensions=self._embedder.spec.dimensions)
        conditions = {
            "service": request.service,
            "environment": request.environment,
            "mode": "preview" if include_drafts else "approved",
            "embedding": self._embedder.spec.fingerprint,
        }
        if not include_drafts:
            conditions["status"] = "approved"
        response = self._client.query_points(
            collection,
            query=vectors[0],
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(key=key, match=models.MatchValue(value=value))
                    for key, value in conditions.items()
                ]
            ),
            limit=request.limit,
            with_payload=True,
            with_vectors=False,
        )
        hits: list[SearchHit] = []
        for point in response.points:
            chunk_id = (point.payload or {}).get("chunk_id")
            if (
                not isinstance(chunk_id, str)
                or chunk_id not in eligible
                or str(point.id) != _point_id(chunk_id)
                or not math.isfinite(point.score)
            ):
                raise KnowledgeIndexError("Index returned an inconsistent result")
            hits.append(SearchHit(chunk=eligible[chunk_id], score=point.score))
        return tuple(hits)
