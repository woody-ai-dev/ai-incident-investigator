import json
from hashlib import sha256
from typing import Literal

from markdown_it import MarkdownIt

from ai_incident_investigator.knowledge.models import (
    RunbookChunk,
    RunbookDocument,
)

INGESTION_VERSION: Literal["markdown-it-sections-v1"] = "markdown-it-sections-v1"
MAX_SECTION_CHARACTERS = 6000


class IngestionError(ValueError):
    """A runbook cannot be prepared using the current ingestion rules."""


def normalize_markdown(content: str) -> str:
    """Normalize line endings and an initial BOM without rewriting content."""
    if content.startswith("\ufeff"):
        content = content[1:]

    return content.replace("\r\n", "\n").replace("\r", "\n")


def _source_lines(content: str) -> list[str]:
    """Split on LF while preserving every line terminator."""
    parts = content.split("\n")
    lines = [part + "\n" for part in parts[:-1]]

    if parts[-1]:
        lines.append(parts[-1])

    return lines


def _section_boundaries(
    content: str,
    *,
    document_id: str,
) -> list[tuple[int, str]]:
    parser = MarkdownIt("commonmark")
    tokens = parser.parse(content)

    boundaries: list[tuple[int, str]] = []

    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.tag != "h2" or token.level != 0:
            continue

        if token.map is None or index + 1 >= len(tokens):
            raise IngestionError(f"Missing heading source information in {document_id}")

        inline = tokens[index + 1]

        if inline.type != "inline":
            raise IngestionError(f"Unexpected heading structure in {document_id}")

        title = inline.content.strip()

        if not title:
            raise IngestionError(
                f"Empty section heading in {document_id} at line {token.map[0] + 1}"
            )

        boundaries.append((token.map[0], title))

    return boundaries


def _chunk_id(
    document: RunbookDocument,
    *,
    ordinal: int,
    start_line: int,
    end_line: int,
) -> str:
    identity = {
        "document": document.metadata.model_dump(mode="json"),
        "document_sha256": document.content_sha256,
        "ingestion_version": INGESTION_VERSION,
        "ordinal": ordinal,
        "start_line": start_line,
        "end_line": end_line,
    }

    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    return f"chunk-{sha256(encoded).hexdigest()}"


def chunk_document(
    document: RunbookDocument,
) -> tuple[RunbookChunk, ...]:
    """Prepare one document; corpus ingestion controls draft eligibility."""
    normalized = normalize_markdown(document.content)

    if not normalized.strip():
        raise IngestionError(f"Runbook has no usable content: {document.metadata.id}")

    lines = _source_lines(normalized)
    boundaries = _section_boundaries(
        normalized,
        document_id=document.metadata.id,
    )

    if not boundaries:
        boundaries = [(0, document.metadata.title)]
    elif boundaries[0][0] > 0:
        first_start, first_title = boundaries[0]
        preamble = "".join(lines[:first_start])

        if preamble.strip():
            boundaries.insert(0, (0, document.metadata.title))
        else:
            # Preserve leading blank lines without creating an empty chunk.
            boundaries[0] = (0, first_title)

    chunks: list[RunbookChunk] = []

    for ordinal, (start, title) in enumerate(boundaries):
        end = boundaries[ordinal + 1][0] if ordinal + 1 < len(boundaries) else len(lines)

        content = "".join(lines[start:end])

        if len(content) > MAX_SECTION_CHARACTERS:
            raise IngestionError(
                f"Section '{title}' in {document.metadata.id} exceeds "
                f"{MAX_SECTION_CHARACTERS} characters; split it into "
                "smaller Markdown sections"
            )

        start_line = start + 1
        end_line = end

        chunks.append(
            RunbookChunk(
                id=_chunk_id(
                    document,
                    ordinal=ordinal,
                    start_line=start_line,
                    end_line=end_line,
                ),
                document=document.metadata,
                document_sha256=document.content_sha256,
                ingestion_version=INGESTION_VERSION,
                section=title,
                ordinal=ordinal,
                start_line=start_line,
                end_line=end_line,
                content=content,
            )
        )

    return tuple(chunks)


def ingest_corpus(
    documents: tuple[RunbookDocument, ...],
    *,
    include_drafts: bool = False,
) -> tuple[RunbookChunk, ...]:
    """Prepare approved documents, or include drafts for explicit preview."""
    document_ids = [document.metadata.id for document in documents]

    if len(document_ids) != len(set(document_ids)):
        raise IngestionError("Corpus document IDs must be unique")

    chunks: list[RunbookChunk] = []

    for document in sorted(
        documents,
        key=lambda item: item.metadata.id,
    ):
        if document.metadata.status != "approved" and not include_drafts:
            continue

        chunks.extend(chunk_document(document))

    return tuple(chunks)
