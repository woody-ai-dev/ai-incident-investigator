from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from ai_incident_investigator.knowledge.models import (
    DocumentMetadata,
    KnowledgeModel,
)

MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 1_000_000
MAX_PDF_PAGES = 50

PositiveLine = Annotated[int, Field(strict=True, ge=1)]


class ExtractionError(ValueError):
    """A source document could not be extracted reliably."""


class DocumentFormat(StrEnum):
    MARKDOWN = "md"
    HTML = "html"
    PDF = "pdf"


class KnowledgeMetadata(DocumentMetadata):
    document_type: Literal[
        "runbook",
        "architecture",
        "configuration",
        "deployment",
        "postmortem",
    ]

    file: Annotated[
        str,
        Field(
            min_length=1,
            max_length=240,
            pattern=(
                r"^(?:[a-z][a-z0-9_-]*/)*"
                r"[a-z][a-z0-9_-]*\.(?:md|html|pdf)$"
            ),
        ),
    ]

    @property
    def source_format(self) -> DocumentFormat:
        suffix = PurePosixPath(self.file).suffix.removeprefix(".")
        return DocumentFormat(suffix)


class KnowledgeCatalog(KnowledgeModel):
    schema_version: Literal[2]
    include_runbooks: bool = True
    documents: tuple[KnowledgeMetadata, ...] = Field(
        default=(),
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_unique_documents(self) -> Self:
        ids = [document.id for document in self.documents]
        files = [document.file for document in self.documents]

        if len(ids) != len(set(ids)):
            raise ValueError("Knowledge document IDs must be unique")

        if len(files) != len(set(files)):
            raise ValueError("Knowledge document files must be unique")

        return self


class MarkdownLocation(KnowledgeModel):
    kind: Literal["markdown"] = "markdown"
    start_line: PositiveLine
    end_line: PositiveLine

    @model_validator(mode="after")
    def validate_lines(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")

        return self


class DoclingLocation(KnowledgeModel):
    kind: Literal["docling"] = "docling"
    item_ref: str = Field(pattern=r"^#/.+", max_length=200)
    pages: tuple[PositiveLine, ...] = ()

    @model_validator(mode="after")
    def validate_pages(self) -> Self:
        if self.pages != tuple(sorted(set(self.pages))):
            raise ValueError("Pages must be unique and sorted")

        return self


SourceLocation = Annotated[
    MarkdownLocation | DoclingLocation,
    Field(discriminator="kind"),
]


class DocumentBlock(KnowledgeModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    kind: Literal["markdown", "text", "code", "table"]
    section: str = Field(min_length=1, max_length=1000)
    content: str = Field(
        min_length=1,
        max_length=MAX_EXTRACTED_CHARACTERS,
    )
    location: SourceLocation


class KnowledgeDocument(KnowledgeModel):
    schema_version: Literal[1] = 1
    metadata: KnowledgeMetadata
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extractor: str = Field(min_length=1, max_length=300)
    blocks: tuple[DocumentBlock, ...] = Field(
        min_length=1,
        max_length=20_000,
    )
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_extraction(self) -> Self:
        total_characters = sum(len(block.content) for block in self.blocks)

        if total_characters > MAX_EXTRACTED_CHARACTERS:
            raise ValueError("Extracted document is too large")

        source_format = self.metadata.source_format

        for block in self.blocks:
            location = block.location

            if source_format == DocumentFormat.MARKDOWN:
                if not isinstance(location, MarkdownLocation):
                    raise ValueError("Markdown requires source-line locations")

                if block.kind != "markdown":
                    raise ValueError("Markdown requires markdown blocks")

                continue

            if not isinstance(location, DoclingLocation):
                raise ValueError("HTML and PDF require Docling locations")

            if source_format == DocumentFormat.PDF and not location.pages:
                raise ValueError("PDF blocks require page provenance")

            if source_format == DocumentFormat.HTML and location.pages:
                raise ValueError("Unrendered HTML must not declare page numbers")

        return self
