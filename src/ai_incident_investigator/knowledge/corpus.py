from hashlib import sha256
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from ai_incident_investigator.knowledge.documents import (
    MAX_SOURCE_BYTES,
    ExtractionError,
    KnowledgeCatalog,
    KnowledgeDocument,
    KnowledgeMetadata,
)
from ai_incident_investigator.knowledge.extraction import (
    DocumentExtractor,
    LocalDocumentExtractor,
)
from ai_incident_investigator.knowledge.loader import CorpusError
from ai_incident_investigator.knowledge.models import RunbookCatalog

MAX_CATALOG_BYTES = 128 * 1024
MAX_CORPUS_BYTES = 50 * 1024 * 1024


def _local_file(root: Path, relative: str) -> Path:
    path = root

    for part in PurePosixPath(relative).parts:
        path = path / part

        if path.is_symlink():
            raise CorpusError(f"Corpus paths must not contain symbolic links: {relative}")

    if not path.is_file():
        raise CorpusError(f"Corpus file does not exist: {relative}")

    return path


def _read_bytes(path: Path, *, limit: int) -> bytes:
    try:
        with path.open("rb") as source:
            content = source.read(limit + 1)
    except OSError as exc:
        raise CorpusError(f"Cannot read corpus file: {path.name}") from exc

    if len(content) > limit:
        raise CorpusError(f"Corpus file is too large: {path.name}")

    if not content:
        raise CorpusError(f"Corpus file is empty: {path.name}")

    return content


def _load_metadata(root: Path) -> tuple[KnowledgeMetadata, ...]:
    try:
        catalog = KnowledgeCatalog.model_validate_json(
            _read_bytes(
                _local_file(root, "knowledge/catalog.json"),
                limit=MAX_CATALOG_BYTES,
            )
        )

        documents = list(catalog.documents)

        if catalog.include_runbooks:
            runbooks = RunbookCatalog.model_validate_json(
                _read_bytes(
                    _local_file(root, "runbooks/catalog.json"),
                    limit=MAX_CATALOG_BYTES,
                )
            )

            documents.extend(
                KnowledgeMetadata.model_validate(
                    {
                        **metadata.model_dump(),
                        "document_type": "runbook",
                        "file": f"runbooks/{metadata.file}",
                    }
                )
                for metadata in runbooks.documents
            )

        combined = KnowledgeCatalog(
            schema_version=2,
            include_runbooks=False,
            documents=tuple(documents),
        )

    except ValidationError as exc:
        raise CorpusError("Invalid knowledge catalog") from exc

    return tuple(
        sorted(
            combined.documents,
            key=lambda document: document.id,
        )
    )


def load_knowledge_corpus(
    root: Path,
    *,
    include_drafts: bool = False,
    extractor: DocumentExtractor | None = None,
) -> tuple[KnowledgeDocument, ...]:
    root = root.resolve()

    if not root.is_dir():
        raise CorpusError("Knowledge root does not exist")

    metadata = _load_metadata(root)
    active_extractor = extractor or LocalDocumentExtractor()

    documents: list[KnowledgeDocument] = []
    total_source_bytes = 0

    for item in metadata:
        if item.status != "approved" and not include_drafts:
            continue

        source = _read_bytes(
            _local_file(root, item.file),
            limit=MAX_SOURCE_BYTES,
        )
        total_source_bytes += len(source)

        if total_source_bytes > MAX_CORPUS_BYTES:
            raise CorpusError("Selected corpus exceeds its total size limit")

        try:
            document = active_extractor.extract(item, source)
        except (ExtractionError, ValidationError) as exc:
            raise CorpusError(f"Cannot prepare document: {item.id}") from exc

        if document.metadata != item:
            raise CorpusError(f"Extractor changed document metadata: {item.id}")

        if document.source_sha256 != sha256(source).hexdigest():
            raise CorpusError(f"Extractor returned an invalid source hash: {item.id}")

        documents.append(document)

    return tuple(documents)
