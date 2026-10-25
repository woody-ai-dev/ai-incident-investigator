import json
from collections.abc import Iterator
from hashlib import sha256
from importlib.metadata import version
from typing import Annotated, Literal, Self

import semchunk
from markdown_it import MarkdownIt
from pydantic import ConfigDict, Field, model_validator

from ai_incident_investigator.knowledge.documents import (
    DocumentBlock,
    KnowledgeDocument,
    KnowledgeMetadata,
    SourceLocation,
)
from ai_incident_investigator.knowledge.models import KnowledgeModel

CHUNKER_VERSION: Literal["retrieval-characters-v1"] = "retrieval-characters-v1"
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]


class ChunkingError(ValueError):
    """A document cannot be split using the selected chunking policy."""


class ChunkingPolicy(KnowledgeModel):
    max_characters: Annotated[int, Field(strict=True, ge=64, le=6000)] = 2000


DEFAULT_POLICY = ChunkingPolicy()


class ChunkSource(KnowledgeModel):
    block_ordinal: NonNegativeInt
    start_char: NonNegativeInt
    end_char: Annotated[int, Field(strict=True, ge=1)]
    location: SourceLocation

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        return self


class RetrievalChunk(KnowledgeModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    id: str = Field(pattern=r"^chunk-[0-9a-f]{64}$")
    document: KnowledgeMetadata
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extractor: str = Field(min_length=1, max_length=300)
    chunker_version: Literal["retrieval-characters-v1"] = CHUNKER_VERSION
    libraries: str = Field(min_length=1, max_length=300)
    policy: ChunkingPolicy
    ordinal: NonNegativeInt
    section: str = Field(min_length=1, max_length=1000)
    content: str = Field(min_length=1, max_length=6000)
    source: ChunkSource
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if not self.content.strip():
            raise ValueError("Chunk must contain usable text")
        if len(self.content) > self.policy.max_characters:
            raise ValueError("Chunk exceeds its character budget")
        if len(self.content) != self.source.end_char - self.source.start_char:
            raise ValueError("Chunk length must match its extracted-text range")
        return self


def _protected_ranges(block: DocumentBlock) -> list[tuple[int, int]]:
    if block.kind in {"code", "table"}:
        return [(0, len(block.content))]
    if block.kind != "markdown":
        return []

    # markdown-it maps lines using LF, including when other Unicode separators occur.
    line_offsets = [0]
    for line in block.content.split("\n"):
        line_offsets.append(min(len(block.content), line_offsets[-1] + len(line) + 1))

    ranges: list[tuple[int, int]] = []
    parser = MarkdownIt("commonmark").enable("table")
    for token in parser.parse(block.content):
        if token.type not in {"fence", "code_block", "table_open"}:
            continue
        if token.map is None:
            raise ChunkingError("Markdown element lacks a source range")
        start, end = (line_offsets[line] for line in token.map)
        if ranges and start < ranges[-1][1]:
            previous_start, previous_end = ranges[-1]
            ranges[-1] = (previous_start, max(previous_end, end))
        else:
            ranges.append((start, end))
    return ranges


def _prose_ranges(text: str, start: int, end: int, limit: int) -> Iterator[tuple[int, int]]:
    if not text[start:end].strip():
        return
    result = semchunk.chunk(text[start:end], limit, len, memoize=False, offsets=True)
    if not isinstance(result, tuple):
        raise ChunkingError("Splitter did not return source offsets")
    contents, ranges = result
    for content, (left, right) in zip(contents, ranges, strict=True):
        if not (0 <= left < right <= end - start):
            raise ChunkingError("Splitter returned an invalid source range")
        if content != text[start + left : start + right] or len(content) > limit:
            raise ChunkingError("Splitter returned invalid chunk content")
        yield start + left, start + right


def _block_ranges(block: DocumentBlock, limit: int) -> Iterator[tuple[int, int]]:
    cursor = 0
    for start, end in _protected_ranges(block):
        yield from _prose_ranges(block.content, cursor, start, limit)
        if end - start > limit:
            raise ChunkingError(
                f"Code or table in section '{block.section}' exceeds {limit} characters; "
                "split the source element or select a larger budget"
            )
        if block.content[start:end].strip():
            yield start, end
        cursor = end
    yield from _prose_ranges(block.content, cursor, len(block.content), limit)


def prepare_document_chunks(
    document: KnowledgeDocument,
    *,
    policy: ChunkingPolicy = DEFAULT_POLICY,
) -> tuple[RetrievalChunk, ...]:
    """Split extracted blocks; character offsets refer to each block's text."""
    libraries = f"semchunk={version('semchunk')};markdown-it-py={version('markdown-it-py')}"
    chunks: list[RetrievalChunk] = []
    for block_ordinal, block in enumerate(document.blocks):
        for start, end in _block_ranges(block, policy.max_characters):
            source = ChunkSource(
                block_ordinal=block_ordinal,
                start_char=start,
                end_char=end,
                location=block.location,
            )
            payload = {
                "document": document.metadata.model_dump(mode="json"),
                "source_sha256": document.source_sha256,
                "extractor": document.extractor,
                "chunker_version": CHUNKER_VERSION,
                "libraries": libraries,
                "policy": policy.model_dump(mode="json"),
                "ordinal": len(chunks),
                "section": block.section,
                "content": block.content[start:end],
                "source": source.model_dump(mode="json"),
                "notes": document.notes,
            }
            identity = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            chunks.append(
                RetrievalChunk.model_validate(
                    {"id": f"chunk-{sha256(identity).hexdigest()}", **payload}
                )
            )
    if not chunks:
        raise ChunkingError(f"Document has no usable chunks: {document.metadata.id}")
    return tuple(chunks)


def prepare_corpus_chunks(
    documents: tuple[KnowledgeDocument, ...],
    *,
    include_drafts: bool = False,
    policy: ChunkingPolicy = DEFAULT_POLICY,
) -> tuple[RetrievalChunk, ...]:
    """Prepare approved documents, or explicitly preview drafts."""
    ids = [document.metadata.id for document in documents]
    if len(ids) != len(set(ids)):
        raise ChunkingError("Corpus document IDs must be unique")

    chunks: list[RetrievalChunk] = []
    for document in sorted(documents, key=lambda item: item.metadata.id):
        if document.metadata.status != "approved" and not include_drafts:
            continue
        chunks.extend(prepare_document_chunks(document, policy=policy))
    return tuple(chunks)
