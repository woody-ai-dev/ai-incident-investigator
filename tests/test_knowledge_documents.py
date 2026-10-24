import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from ai_incident_investigator.knowledge import corpus, documents
from ai_incident_investigator.knowledge.corpus import load_knowledge_corpus
from ai_incident_investigator.knowledge.documents import (
    DoclingLocation,
    DocumentBlock,
    DocumentFormat,
    ExtractionError,
    KnowledgeCatalog,
    KnowledgeDocument,
    KnowledgeMetadata,
    MarkdownLocation,
)
from ai_incident_investigator.knowledge.extraction import LocalDocumentExtractor
from ai_incident_investigator.knowledge.ingestion import normalize_markdown
from ai_incident_investigator.knowledge.loader import CorpusError
from ai_incident_investigator.knowledge.models import RunbookCatalog, RunbookMetadata
from scripts import ingest_knowledge as cli

SOURCE = b"# Example\n\n## Checks\nInspect logs.\n"


def make_metadata(
    *,
    document_id: str = "example",
    file: str = "source.md",
    approved: bool = False,
) -> KnowledgeMetadata:
    return KnowledgeMetadata(
        id=document_id,
        title="Example document",
        document_type="runbook",
        service="order-service",
        environment="local",
        owner="test-owner",
        version=1,
        status="approved" if approved else "draft",
        reviewed_by="test-reviewer" if approved else None,
        file=file,
    )


def write_catalog(
    root: Path,
    metadata: tuple[KnowledgeMetadata, ...],
    *,
    include_runbooks: bool = False,
) -> None:
    destination = root / "knowledge"
    destination.mkdir(parents=True, exist_ok=True)
    catalog = KnowledgeCatalog(
        schema_version=2,
        include_runbooks=include_runbooks,
        documents=metadata,
    )
    (destination / "catalog.json").write_text(catalog.model_dump_json(), encoding="utf-8")


def write_source(root: Path, metadata: KnowledgeMetadata, source: bytes = SOURCE) -> None:
    path = root / metadata.file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source)


def write_legacy_runbook(root: Path) -> RunbookMetadata:
    metadata = RunbookMetadata(
        id="legacy-runbook",
        title="Legacy runbook",
        service="order-service",
        environment="local",
        owner="legacy-owner",
        version=3,
        status="approved",
        reviewed_by="legacy-reviewer",
        file="legacy-runbook.md",
    )
    destination = root / "runbooks"
    destination.mkdir()
    (destination / "catalog.json").write_text(
        RunbookCatalog(schema_version=1, documents=(metadata,)).model_dump_json(),
        encoding="utf-8",
    )
    (destination / metadata.file).write_bytes(SOURCE)
    return metadata


@pytest.mark.parametrize(
    "file",
    [
        "../source.md",
        "/source.md",
        "knowledge/../source.md",
        "knowledge//source.md",
        "knowledge/./source.md",
        "knowledge\\source.md",
        "source.exe",
        "source.MD",
    ],
)
def test_rejects_invalid_source_paths(file: str) -> None:
    with pytest.raises(ValidationError):
        make_metadata(file=file)


@pytest.mark.parametrize(
    ("file", "expected"),
    [
        ("knowledge/nested/source_notes.md", DocumentFormat.MARKDOWN),
        ("knowledge/service.html", DocumentFormat.HTML),
        ("knowledge/settings.pdf", DocumentFormat.PDF),
    ],
)
def test_source_format_matches_the_declared_extension(file: str, expected: DocumentFormat) -> None:
    assert make_metadata(file=file).source_format == expected


@pytest.mark.parametrize("duplicate", ["id", "file"])
def test_catalog_rejects_duplicate_identity(duplicate: str) -> None:
    original = make_metadata()
    second = make_metadata(document_id="other", file="other.md").model_dump()
    second[duplicate] = original.model_dump()[duplicate]

    with pytest.raises(ValidationError, match="must be unique"):
        KnowledgeCatalog.model_validate(
            {
                "schema_version": 2,
                "documents": [original.model_dump(), second],
            }
        )


@pytest.mark.parametrize(
    "location",
    [
        {"kind": "markdown", "start_line": 2, "end_line": 1},
        {"kind": "markdown", "start_line": True, "end_line": 2},
        {"kind": "docling", "item_ref": "#/texts/0", "pages": (2, 1)},
        {"kind": "docling", "item_ref": "#/texts/0", "pages": (1, 1)},
        {"kind": "docling", "item_ref": "#/texts/0", "pages": (0,)},
    ],
)
def test_locations_reject_ambiguous_or_invalid_coordinates(
    location: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        DocumentBlock.model_validate(
            {
                "kind": "text",
                "section": "Checks",
                "content": "Inspect logs.",
                "location": location,
            }
        )


@pytest.mark.parametrize(
    ("file", "location", "block_kind", "message"),
    [
        (
            "source.pdf",
            DoclingLocation(item_ref="#/texts/0"),
            "text",
            "page provenance",
        ),
        (
            "source.html",
            DoclingLocation(item_ref="#/texts/0", pages=(1,)),
            "text",
            "page numbers",
        ),
        (
            "source.html",
            MarkdownLocation(start_line=1, end_line=1),
            "text",
            "Docling locations",
        ),
        (
            "source.md",
            DoclingLocation(item_ref="#/texts/0"),
            "markdown",
            "source-line locations",
        ),
        (
            "source.md",
            MarkdownLocation(start_line=1, end_line=1),
            "text",
            "markdown blocks",
        ),
    ],
)
def test_document_contract_rejects_locations_incompatible_with_source(
    file: str,
    location: MarkdownLocation | DoclingLocation,
    block_kind: Literal["markdown", "text"],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        KnowledgeDocument(
            metadata=make_metadata(file=file),
            source_sha256="0" * 64,
            extractor="test",
            blocks=(
                DocumentBlock(
                    kind=block_kind,
                    section="Checks",
                    content="Inspect logs.",
                    location=location,
                ),
            ),
        )


def test_document_contract_limits_total_extracted_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(documents, "MAX_EXTRACTED_CHARACTERS", 10)
    block = DocumentBlock(
        kind="markdown",
        section="Checks",
        content="123456",
        location=MarkdownLocation(start_line=1, end_line=1),
    )

    with pytest.raises(ValidationError, match="too large"):
        KnowledgeDocument(
            metadata=make_metadata(),
            source_sha256="0" * 64,
            extractor="test",
            blocks=(block, block),
        )


def test_markdown_adapter_preserves_original_hash_text_and_lines() -> None:
    metadata = make_metadata(file="knowledge/nested/source_notes.md")
    source = b"\xef\xbb\xbf# Example\r\n\r\n## Checks\r\nKeep  spaces.\r\n"

    document = LocalDocumentExtractor().extract(metadata, source)

    assert document.metadata == metadata
    assert document.source_sha256 == sha256(source).hexdigest()
    assert "markdown-it-py=" in document.extractor
    assert "".join(block.content for block in document.blocks) == normalize_markdown(
        source.decode("utf-8")
    )
    assert [block.location.model_dump() for block in document.blocks] == [
        {"kind": "markdown", "start_line": 1, "end_line": 2},
        {"kind": "markdown", "start_line": 3, "end_line": 4},
    ]


def test_loader_excludes_drafts_without_opening_their_sources(tmp_path: Path) -> None:
    write_catalog(tmp_path, (make_metadata(),))

    assert load_knowledge_corpus(tmp_path) == ()


@pytest.mark.parametrize("approved", [False, True])
def test_loader_selects_approved_documents_and_explicit_previews(
    tmp_path: Path, approved: bool
) -> None:
    metadata = make_metadata(approved=approved)
    write_catalog(tmp_path, (metadata,))
    write_source(tmp_path, metadata)

    result = load_knowledge_corpus(tmp_path, include_drafts=not approved)

    assert len(result) == 1
    assert result[0].metadata == metadata


def test_loader_returns_documents_in_stable_id_order(tmp_path: Path) -> None:
    second = make_metadata(document_id="second", file="second.md", approved=True)
    first = make_metadata(document_id="first", file="first.md", approved=True)
    write_catalog(tmp_path, (second, first))
    write_source(tmp_path, first)
    write_source(tmp_path, second)

    assert [document.metadata.id for document in load_knowledge_corpus(tmp_path)] == [
        "first",
        "second",
    ]


def test_loader_imports_legacy_runbook_metadata_without_changing_review(
    tmp_path: Path,
) -> None:
    write_catalog(tmp_path, (), include_runbooks=True)
    legacy = write_legacy_runbook(tmp_path)

    (document,) = load_knowledge_corpus(tmp_path)

    assert document.metadata.document_type == "runbook"
    assert document.metadata.file == "runbooks/legacy-runbook.md"
    assert document.metadata.model_dump(exclude={"document_type", "file"}) == (
        legacy.model_dump(exclude={"file"})
    )


@pytest.mark.parametrize("duplicate", ["id", "file"])
def test_loader_rejects_duplicates_across_general_and_runbook_catalogs(
    tmp_path: Path, duplicate: str
) -> None:
    legacy = write_legacy_runbook(tmp_path)
    general = make_metadata(
        document_id=legacy.id if duplicate == "id" else "other",
        file=f"runbooks/{legacy.file}" if duplicate == "file" else "other.md",
    )
    write_catalog(tmp_path, (general,), include_runbooks=True)

    with pytest.raises(CorpusError, match="Invalid knowledge catalog"):
        load_knowledge_corpus(tmp_path)


def test_loader_accepts_an_explicit_empty_corpus(tmp_path: Path) -> None:
    write_catalog(tmp_path, ())

    assert load_knowledge_corpus(tmp_path) == ()


def test_loader_reports_missing_root(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="root does not exist"):
        load_knowledge_corpus(tmp_path / "missing")


@pytest.mark.parametrize("catalog_content", [b"{", b"\xff"])
def test_loader_reports_malformed_catalog(tmp_path: Path, catalog_content: bytes) -> None:
    write_catalog(tmp_path, ())
    (tmp_path / "knowledge/catalog.json").write_bytes(catalog_content)

    with pytest.raises(CorpusError, match="Invalid knowledge catalog"):
        load_knowledge_corpus(tmp_path)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (b"", "file is empty"),
        (b"  \n\t", "Cannot prepare document"),
        (b"\xff", "Cannot prepare document"),
    ],
)
def test_loader_rejects_selected_empty_or_invalid_markdown(
    tmp_path: Path, source: bytes, message: str
) -> None:
    metadata = make_metadata(approved=True)
    write_catalog(tmp_path, (metadata,))
    write_source(tmp_path, metadata, source)

    with pytest.raises(CorpusError, match=message):
        load_knowledge_corpus(tmp_path)


def test_loader_reports_missing_selected_source(tmp_path: Path) -> None:
    write_catalog(tmp_path, (make_metadata(approved=True),))

    with pytest.raises(CorpusError, match="does not exist"):
        load_knowledge_corpus(tmp_path)


@pytest.mark.parametrize("linked_path", ["source.md", "knowledge/catalog.json"])
def test_loader_rejects_symbolic_links_to_files(tmp_path: Path, linked_path: str) -> None:
    metadata = make_metadata(approved=True)
    write_catalog(tmp_path, (metadata,))
    write_source(tmp_path, metadata)
    path = tmp_path / linked_path
    target = path.with_suffix(".original")
    path.rename(target)
    path.symlink_to(target)

    with pytest.raises(CorpusError, match="symbolic links"):
        load_knowledge_corpus(tmp_path)


def test_loader_rejects_symbolic_links_in_source_parent_directories(
    tmp_path: Path,
) -> None:
    metadata = make_metadata(file="sources/example.md", approved=True)
    write_catalog(tmp_path, (metadata,))
    real_directory = tmp_path / "real-sources"
    real_directory.mkdir()
    (real_directory / "example.md").write_bytes(SOURCE)
    (tmp_path / "sources").symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(CorpusError, match="symbolic links"):
        load_knowledge_corpus(tmp_path)


@pytest.mark.parametrize(
    ("limit_name", "limit", "message"),
    [
        ("MAX_CATALOG_BYTES", 1, "too large"),
        ("MAX_SOURCE_BYTES", len(SOURCE) - 1, "too large"),
        ("MAX_CORPUS_BYTES", len(SOURCE) - 1, "total size limit"),
    ],
)
def test_loader_enforces_catalog_source_and_corpus_size_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    limit: int,
    message: str,
) -> None:
    metadata = make_metadata(approved=True)
    write_catalog(tmp_path, (metadata,))
    write_source(tmp_path, metadata)
    monkeypatch.setattr(corpus, limit_name, limit)

    with pytest.raises(CorpusError, match=message):
        load_knowledge_corpus(tmp_path)


def test_corpus_size_limit_counts_all_selected_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = make_metadata(document_id="first", file="first.md", approved=True)
    second = make_metadata(document_id="second", file="second.md", approved=True)
    write_catalog(tmp_path, (first, second))
    write_source(tmp_path, first)
    write_source(tmp_path, second)
    monkeypatch.setattr(corpus, "MAX_CORPUS_BYTES", 2 * len(SOURCE) - 1)

    with pytest.raises(CorpusError, match="total size limit"):
        load_knowledge_corpus(tmp_path)


@pytest.mark.parametrize("mismatch", ["metadata", "hash"])
def test_loader_rejects_extractor_metadata_or_hash_mismatch(tmp_path: Path, mismatch: str) -> None:
    metadata = make_metadata(approved=True)
    write_catalog(tmp_path, (metadata,))
    write_source(tmp_path, metadata)

    class MismatchedExtractor:
        def extract(self, metadata: KnowledgeMetadata, source: bytes) -> KnowledgeDocument:
            document = LocalDocumentExtractor().extract(metadata, source)

            if mismatch == "metadata":
                return document.model_copy(
                    update={"metadata": make_metadata(document_id="other", approved=True)}
                )

            return document.model_copy(update={"source_sha256": "0" * 64})

    with pytest.raises(CorpusError, match="metadata|hash"):
        load_knowledge_corpus(tmp_path, extractor=MismatchedExtractor())


def test_loader_preserves_extraction_failure_as_the_error_cause(tmp_path: Path) -> None:
    metadata = make_metadata(approved=True)
    write_catalog(tmp_path, (metadata,))
    write_source(tmp_path, metadata)

    class FailingExtractor:
        def extract(self, metadata: KnowledgeMetadata, source: bytes) -> KnowledgeDocument:
            raise ExtractionError("Unsupported source layout")

    with pytest.raises(CorpusError, match="Cannot prepare document: example") as error:
        load_knowledge_corpus(tmp_path, extractor=FailingExtractor())

    assert isinstance(error.value.__cause__, ExtractionError)


@pytest.mark.parametrize(
    ("include_drafts", "expected_mode", "expected_count"),
    [(False, "approved", 0), (True, "preview", 1)],
)
def test_cli_outputs_json_for_approved_and_preview_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    include_drafts: bool,
    expected_mode: str,
    expected_count: int,
) -> None:
    metadata = make_metadata()
    write_catalog(tmp_path, (metadata,))
    write_source(tmp_path, metadata)
    arguments = ["ingest_knowledge", "--root", str(tmp_path)]

    if include_drafts:
        arguments.append("--include-drafts")

    monkeypatch.setattr(sys, "argv", arguments)

    cli.main()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["schema_version"] == 1
    assert payload["mode"] == expected_mode
    assert payload["document_count"] == expected_count
    assert payload["block_count"] == 2 * expected_count
    assert len(payload["documents"]) == expected_count

    if include_drafts:
        assert payload["documents"][0]["source_sha256"] == sha256(SOURCE).hexdigest()


def test_cli_reports_missing_catalog_to_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["ingest_knowledge", "--root", str(tmp_path)])

    with pytest.raises(SystemExit) as error:
        cli.main()

    captured = capsys.readouterr()
    assert error.value.code == 1
    assert captured.out == ""
    assert "Knowledge ingestion failed:" in captured.err
