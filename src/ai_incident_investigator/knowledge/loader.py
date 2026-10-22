from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from ai_incident_investigator.knowledge.models import (
    RunbookCatalog,
    RunbookDocument,
)

MAX_CATALOG_BYTES = 128 * 1024
MAX_RUNBOOK_BYTES = 64 * 1024


class CorpusError(ValueError):
    """The local runbook corpus is missing or invalid."""


def _read_file(path: Path, *, max_bytes: int) -> bytes:
    try:
        with path.open("rb") as source:
            content = source.read(max_bytes + 1)
    except OSError as exc:
        raise CorpusError(f"Cannot read corpus file: {path.name}") from exc

    if len(content) > max_bytes:
        raise CorpusError(f"Corpus file is too large: {path.name}")

    return content


def _decode_utf8(content: bytes, *, filename: str) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorpusError(f"Corpus file must use UTF-8: {filename}") from exc


def load_corpus(root: Path) -> tuple[RunbookDocument, ...]:
    """Load and validate every catalog entry, including draft documents."""
    root = root.resolve()

    if not root.is_dir():
        raise CorpusError("Runbook directory does not exist")

    catalog_path = root / "catalog.json"

    if catalog_path.is_symlink():
        raise CorpusError("Runbook catalog must not be a symbolic link")

    raw_catalog = _read_file(
        catalog_path,
        max_bytes=MAX_CATALOG_BYTES,
    )
    catalog_text = _decode_utf8(
        raw_catalog,
        filename=catalog_path.name,
    )

    try:
        catalog = RunbookCatalog.model_validate_json(catalog_text)
    except ValidationError as exc:
        raise CorpusError("Invalid runbook catalog") from exc

    documents: list[RunbookDocument] = []

    for metadata in catalog.documents:
        path = root / metadata.file

        if path.is_symlink():
            raise CorpusError(f"Runbook file must not be a symbolic link: {metadata.file}")

        raw_content = _read_file(
            path,
            max_bytes=MAX_RUNBOOK_BYTES,
        )
        content = _decode_utf8(
            raw_content,
            filename=metadata.file,
        )

        if not content.strip():
            raise CorpusError(f"Runbook must not be empty: {metadata.file}")

        documents.append(
            RunbookDocument(
                metadata=metadata,
                content=content,
                content_sha256=sha256(raw_content).hexdigest(),
            )
        )

    return tuple(sorted(documents, key=lambda document: document.metadata.id))


def approved_runbooks(
    documents: tuple[RunbookDocument, ...],
    *,
    service: str,
    environment: str,
) -> tuple[RunbookDocument, ...]:
    """Select approved documents for an exact service/environment scope."""
    return tuple(
        document
        for document in documents
        if document.metadata.status == "approved"
        and document.metadata.service == service
        and document.metadata.environment == environment
    )
