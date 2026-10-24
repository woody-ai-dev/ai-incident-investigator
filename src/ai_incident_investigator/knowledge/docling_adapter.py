from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal

from ai_incident_investigator.knowledge.documents import (
    MAX_EXTRACTED_CHARACTERS,
    MAX_PDF_PAGES,
    MAX_SOURCE_BYTES,
    DoclingLocation,
    DocumentBlock,
    DocumentFormat,
    ExtractionError,
    KnowledgeDocument,
    KnowledgeMetadata,
)

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter
    from docling_core.types.doc.document import DoclingDocument

EXTRACTOR_VERSION = "docling-native-blocks-v1"


def _create_converter() -> "DocumentConverter":
    from docling.datamodel.backend_options import HTMLBackendOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import NativePdfPipelineOptions
    from docling.document_converter import (
        DocumentConverter,
        HTMLFormatOption,
        NativePdfFormatOption,
    )

    return DocumentConverter(
        allowed_formats=[InputFormat.HTML, InputFormat.PDF],
        format_options={
            InputFormat.HTML: HTMLFormatOption(
                backend_options=HTMLBackendOptions.model_validate(
                    {
                        "render_page": False,
                        "fetch_images": False,
                        "enable_remote_fetch": False,
                        "enable_local_fetch": False,
                        "add_title": False,
                        "infer_furniture": False,
                    }
                ),
            ),
            InputFormat.PDF: NativePdfFormatOption(
                pipeline_options=NativePdfPipelineOptions(
                    generate_page_images=False,
                    generate_picture_images=False,
                    parser_threads=1,
                    document_timeout=30.0,
                ),
            ),
        },
    )


def _prepare_html(source: bytes, *, filename: str) -> bytes:
    from bs4 import BeautifulSoup

    try:
        content = source.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExtractionError(f"HTML must use UTF-8: {filename}") from exc

    soup = BeautifulSoup(content, "html.parser")
    for tag in soup.find_all(["script", "style", "nav"]):
        if not tag.decomposed:
            tag.decompose()

    return soup.encode("utf-8")


def _extractor_fingerprint() -> str:
    packages = ("docling", "docling-core", "docling-parse", "beautifulsoup4")
    return ";".join([EXTRACTOR_VERSION, *(f"{name}={version(name)}" for name in packages)])


def _extract_blocks(
    document: "DoclingDocument",
    *,
    metadata: KnowledgeMetadata,
) -> tuple[DocumentBlock, ...]:
    from docling_core.types.doc.items.code import CodeItem
    from docling_core.types.doc.items.table.table import TableItem
    from docling_core.types.doc.items.text import SectionHeaderItem, TextItem, TitleItem

    blocks: list[DocumentBlock] = []
    section = metadata.title
    table_level: int | None = None
    total_characters = 0

    for item, level in document.iterate_items():
        # A serialized table already includes the content of its rich cells.
        if table_level is not None:
            if level > table_level:
                continue
            table_level = None

        kind: Literal["text", "code", "table"]
        if isinstance(item, TableItem):
            content = item.export_to_markdown(doc=document)
            kind = "table"
            table_level = level
        elif isinstance(item, TextItem):
            content = item.text
            kind = "code" if isinstance(item, CodeItem) else "text"
        else:
            continue

        if not content.strip():
            continue
        if isinstance(item, (SectionHeaderItem, TitleItem)):
            section = content

        pages = (
            tuple(sorted({provenance.page_no for provenance in item.prov}))
            if metadata.source_format == DocumentFormat.PDF
            else ()
        )
        if metadata.source_format == DocumentFormat.PDF and not pages:
            raise ExtractionError(f"PDF content lacks page provenance: {metadata.file}")

        total_characters += len(content)
        if total_characters > MAX_EXTRACTED_CHARACTERS or len(blocks) >= 20_000:
            raise ExtractionError(f"Extracted document is too large: {metadata.file}")

        blocks.append(
            DocumentBlock(
                kind=kind,
                section=section,
                content=content,
                location=DoclingLocation(item_ref=item.self_ref, pages=pages),
            )
        )

    if not blocks:
        raise ExtractionError(f"Document has no usable text: {metadata.file}")
    return tuple(blocks)


def extract_docling(metadata: KnowledgeMetadata, source: bytes) -> KnowledgeDocument:
    """Extract local HTML or native PDF text with no model-based processing."""
    if metadata.source_format not in {DocumentFormat.HTML, DocumentFormat.PDF}:
        raise ExtractionError(f"Unsupported Docling source format: {metadata.file}")
    if not source or len(source) > MAX_SOURCE_BYTES:
        raise ExtractionError(f"Document is empty or too large: {metadata.file}")

    try:
        from docling.datamodel.base_models import (
            ConversionStatus,
            DocumentStream,
            InputFormat,
        )

        fingerprint = _extractor_fingerprint()
        prepared = (
            _prepare_html(source, filename=metadata.file)
            if metadata.source_format == DocumentFormat.HTML
            else source
        )
        converter = _create_converter()
    except (ImportError, PackageNotFoundError) as exc:
        raise ExtractionError(
            "HTML/PDF extraction requires the ingestion extra; "
            "run uv sync --locked --extra ingestion"
        ) from exc

    expected_format = (
        InputFormat.HTML if metadata.source_format == DocumentFormat.HTML else InputFormat.PDF
    )
    stream = DocumentStream(
        name=PurePosixPath(metadata.file).name,
        stream=BytesIO(prepared),
    )
    try:
        result = converter.convert(
            stream,
            raises_on_error=False,
            max_num_pages=MAX_PDF_PAGES,
            max_file_size=MAX_SOURCE_BYTES,
        )
    except Exception as exc:
        raise ExtractionError(f"Document conversion failed: {metadata.file}") from exc

    if result.status != ConversionStatus.SUCCESS:
        raise ExtractionError(
            f"Document conversion did not complete successfully "
            f"({result.status.value}): {metadata.file}"
        )
    if result.input.format != expected_format:
        raise ExtractionError(f"Document content does not match its format: {metadata.file}")

    try:
        blocks = _extract_blocks(result.document, metadata=metadata)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Cannot prepare document blocks: {metadata.file}") from exc

    notes = (
        (
            "HTML navigation, scripts, and styles are removed before extraction.",
            "HTML is not rendered; image content and page locations are unavailable.",
            "Docling may normalize outer whitespace in HTML code blocks.",
        )
        if metadata.source_format == DocumentFormat.HTML
        else (
            "Native PDF text only; OCR, reading-order analysis, and table detection are disabled.",
        )
    )
    return KnowledgeDocument(
        metadata=metadata,
        source_sha256=sha256(source).hexdigest(),
        extractor=fingerprint,
        blocks=blocks,
        notes=notes,
    )
