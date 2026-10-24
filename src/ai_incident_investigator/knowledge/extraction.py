from hashlib import sha256
from importlib.metadata import version
from typing import Protocol

from pydantic import ValidationError

from ai_incident_investigator.knowledge.documents import (
    DocumentBlock,
    DocumentFormat,
    ExtractionError,
    KnowledgeDocument,
    KnowledgeMetadata,
    MarkdownLocation,
)
from ai_incident_investigator.knowledge.ingestion import (
    INGESTION_VERSION,
    IngestionError,
    chunk_document,
)
from ai_incident_investigator.knowledge.models import (
    RunbookDocument,
    RunbookMetadata,
)


class DocumentExtractor(Protocol):
    def extract(
        self,
        metadata: KnowledgeMetadata,
        source: bytes,
    ) -> KnowledgeDocument: ...


class LocalDocumentExtractor:
    def extract(
        self,
        metadata: KnowledgeMetadata,
        source: bytes,
    ) -> KnowledgeDocument:
        if metadata.source_format == DocumentFormat.MARKDOWN:
            return self._extract_markdown(metadata, source)

        from ai_incident_investigator.knowledge.docling_adapter import (
            extract_docling,
        )

        return extract_docling(metadata, source)

    def _extract_markdown(
        self,
        metadata: KnowledgeMetadata,
        source: bytes,
    ) -> KnowledgeDocument:
        try:
            content = source.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExtractionError(f"Markdown must use UTF-8: {metadata.file}") from exc

        source_hash = sha256(source).hexdigest()

        runbook_metadata = RunbookMetadata.model_validate(
            {
                **metadata.model_dump(
                    exclude={"document_type", "file"},
                ),
                "file": f"{metadata.id}.md",
            }
        )

        try:
            runbook = RunbookDocument(
                metadata=runbook_metadata,
                content=content,
                content_sha256=source_hash,
            )
            chunks = chunk_document(runbook)
        except (IngestionError, ValidationError) as exc:
            raise ExtractionError(str(exc)) from exc

        return KnowledgeDocument(
            metadata=metadata,
            source_sha256=source_hash,
            extractor=(f"{INGESTION_VERSION};markdown-it-py={version('markdown-it-py')}"),
            blocks=tuple(
                DocumentBlock(
                    kind="markdown",
                    section=chunk.section,
                    content=chunk.content,
                    location=MarkdownLocation(
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                    ),
                )
                for chunk in chunks
            ),
        )
