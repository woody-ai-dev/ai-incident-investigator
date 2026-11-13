from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ai_incident_investigator.knowledge.models import Identifier, KnowledgeModel
from ai_incident_investigator.knowledge.retrieval_chunks import RetrievalChunk
from ai_incident_investigator.knowledge.vector_index import SearchHit, SearchRequest

ChunkId = Annotated[str, Field(pattern=r"^chunk-[0-9a-f]{64}$")]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]


class ContextError(ValueError):
    """Retrieval results cannot form a valid knowledge context."""


class ContextPolicy(KnowledgeModel):
    max_bytes: Annotated[int, Field(strict=True, ge=512, le=24_000)] = 12_000
    max_chunks: Annotated[int, Field(strict=True, ge=1, le=20)] = 5


DEFAULT_CONTEXT_POLICY = ContextPolicy()


class KnowledgeContext(KnowledgeModel):
    schema_version: Literal[1] = 1
    purpose: Literal["operational_guidance"] = "operational_guidance"
    mode: Literal["approved", "preview"]
    service: Identifier
    environment: Identifier
    chunks: tuple[SearchHit, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def validate_chunks(self) -> Self:
        ids = [hit.chunk.id for hit in self.chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("Context chunk IDs must be unique")

        for hit in self.chunks:
            metadata = hit.chunk.document
            if metadata.service != self.service or metadata.environment != self.environment:
                raise ValueError("Context chunks must match its exact service and environment")
            if self.mode == "approved" and metadata.status != "approved":
                raise ValueError("Approved context cannot contain draft documents")

        return self

    def to_json(self) -> str:
        """Return the exact compact JSON whose UTF-8 bytes are budgeted."""
        return self.model_dump_json()

    @property
    def payload_bytes(self) -> int:
        return len(self.to_json().encode("utf-8"))


class OmittedChunk(KnowledgeModel):
    chunk_id: ChunkId
    reason: Literal["duplicate", "chunk_limit", "byte_budget", "inapplicable"]


class ContextAssembly(KnowledgeModel):
    context: KnowledgeContext
    policy: ContextPolicy
    payload_bytes: NonNegativeInt
    omitted: tuple[OmittedChunk, ...] = ()

    @model_validator(mode="after")
    def validate_budget(self) -> Self:
        if self.payload_bytes != self.context.payload_bytes:
            raise ValueError("Context byte count must match its compact JSON")
        if self.payload_bytes > self.policy.max_bytes:
            raise ValueError("Context exceeds its byte budget")
        if len(self.context.chunks) > self.policy.max_chunks:
            raise ValueError("Context exceeds its chunk limit")
        return self


def assemble_context(
    request: SearchRequest,
    hits: tuple[SearchHit, ...],
    *,
    policy: ContextPolicy = DEFAULT_CONTEXT_POLICY,
    include_drafts: bool = False,
) -> ContextAssembly:
    """Keep whole ranked chunks within an exact JSON budget, retaining provenance."""
    if len(hits) > request.limit:
        raise ContextError("Search returned more chunks than requested")

    known: dict[str, RetrievalChunk] = {}
    for hit in hits:
        chunk = hit.chunk
        metadata = chunk.document

        if metadata.service != request.service or metadata.environment != request.environment:
            raise ContextError("Search returned an out-of-scope chunk")
        if not include_drafts and metadata.status != "approved":
            raise ContextError("Approved context cannot contain draft documents")

        previous = known.get(chunk.id)
        if previous is not None and previous != chunk:
            raise ContextError("One chunk ID refers to different chunk content or metadata")
        known[chunk.id] = chunk

    mode: Literal["approved", "preview"] = "preview" if include_drafts else "approved"
    context = KnowledgeContext(
        mode=mode,
        service=request.service,
        environment=request.environment,
    )
    if context.payload_bytes > policy.max_bytes:
        raise ContextError("Context metadata exceeds its byte budget")

    seen: set[str] = set()
    omitted: list[OmittedChunk] = []
    for hit in hits:
        chunk_id = hit.chunk.id

        if chunk_id in seen:
            omitted.append(OmittedChunk(chunk_id=chunk_id, reason="duplicate"))
            continue
        seen.add(chunk_id)

        if len(context.chunks) >= policy.max_chunks:
            omitted.append(OmittedChunk(chunk_id=chunk_id, reason="chunk_limit"))
            continue

        candidate = KnowledgeContext(
            mode=mode,
            service=request.service,
            environment=request.environment,
            chunks=(*context.chunks, hit),
        )
        if candidate.payload_bytes > policy.max_bytes:
            omitted.append(OmittedChunk(chunk_id=chunk_id, reason="byte_budget"))
            continue
        context = candidate

    return ContextAssembly(
        context=context,
        policy=policy,
        payload_bytes=context.payload_bytes,
        omitted=tuple(omitted),
    )
