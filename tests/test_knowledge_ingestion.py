import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Literal

import pytest

from ai_incident_investigator.knowledge.ingestion import (
    MAX_SECTION_CHARACTERS,
    IngestionError,
    chunk_document,
    ingest_corpus,
    normalize_markdown,
)
from ai_incident_investigator.knowledge.loader import load_corpus
from ai_incident_investigator.knowledge.models import (
    RunbookCatalog,
    RunbookDocument,
    RunbookMetadata,
)
from scripts import ingest_runbooks as cli

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "knowledge"


def make_document(
    content: str,
    *,
    document_id: str = "test-runbook",
    status: Literal["draft", "approved"] = "draft",
    environment: str = "local",
) -> RunbookDocument:
    return RunbookDocument(
        metadata=RunbookMetadata(
            id=document_id,
            title="Test runbook",
            service="order-service",
            environment=environment,
            owner="test-owner",
            version=1,
            status=status,
            reviewed_by="test-reviewer" if status == "approved" else None,
            file=f"{document_id}.md",
        ),
        content=content,
        content_sha256=sha256(content.encode("utf-8")).hexdigest(),
    )


def write_corpus(root: Path) -> None:
    document = make_document("# Example\n\n## Checks\nInspect logs.\n")
    catalog = RunbookCatalog(
        schema_version=1,
        documents=(document.metadata,),
    )

    (root / "catalog.json").write_text(
        catalog.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (root / document.metadata.file).write_text(
        document.content,
        encoding="utf-8",
    )


def test_normalizes_bom_and_line_endings_only() -> None:
    source = "\ufeff# Title\r\n\r\nKeep  two spaces.\r    command\r"

    normalized = normalize_markdown(source)

    assert normalized == ("# Title\n\nKeep  two spaces.\n    command\n")


def test_normalization_is_idempotent() -> None:
    source = "\ufeff# Title\r\n\r\nBody.\r\n"

    once = normalize_markdown(source)

    assert normalize_markdown(once) == once


def test_preserves_internal_bom() -> None:
    source = "# Title\n\nExample: \ufeff inside content.\n"

    assert normalize_markdown(source) == source


def test_splits_on_top_level_h2_headings() -> None:
    document = make_document(
        "# Example\n\n"
        "## Symptoms\n"
        "Timeout observed.\n\n"
        "### Additional context\n"
        "Keep this inside Symptoms.\n\n"
        "## Checks\n"
        "Inspect logs.\n"
    )

    chunks = chunk_document(document)

    assert [chunk.section for chunk in chunks] == [
        "Test runbook",
        "Symptoms",
        "Checks",
    ]
    assert "### Additional context" in chunks[1].content
    assert [chunk.ordinal for chunk in chunks] == [0, 1, 2]


def test_supports_setext_level_two_headings() -> None:
    document = make_document("# Example\n\nChecks\n------\nInspect logs.\n")

    chunks = chunk_document(document)

    assert [chunk.section for chunk in chunks] == [
        "Test runbook",
        "Checks",
    ]
    assert chunks[1].content.startswith("Checks\n------\n")


def test_ignores_headings_inside_code_fences() -> None:
    document = make_document((FIXTURES / "fenced-code.md").read_text(encoding="utf-8"))

    chunks = chunk_document(document)

    assert [chunk.section for chunk in chunks] == [
        "Test runbook",
        "What to inspect",
        "Operational limits",
    ]
    assert "## This is not a section" in chunks[1].content
    assert "## This is not a section either" in chunks[1].content
    assert "keep  two spaces" in chunks[1].content


def test_ignores_headings_inside_indented_code() -> None:
    document = make_document(
        "## Checks\n\n"
        "    ## This is code\n"
        "    inspect_logs()\n\n"
        "## Limits\n"
        "Do not retry automatically.\n"
    )

    chunks = chunk_document(document)

    assert [chunk.section for chunk in chunks] == [
        "Checks",
        "Limits",
    ]
    assert "    ## This is code" in chunks[0].content


def test_ignores_nested_headings() -> None:
    document = make_document(
        "# Example\n\n"
        "> ## Quoted heading\n"
        "> Quoted text.\n\n"
        "- List item\n\n"
        "  ## Nested heading\n\n"
        "  Nested text.\n\n"
        "## Checks\n"
        "Inspect logs.\n"
    )

    chunks = chunk_document(document)

    assert [chunk.section for chunk in chunks] == [
        "Test runbook",
        "Checks",
    ]
    assert "> ## Quoted heading" in chunks[0].content
    assert "  ## Nested heading" in chunks[0].content


def test_unclosed_fence_continues_to_end_of_document() -> None:
    document = make_document("## Example\n```text\n## This remains code\n")

    chunks = chunk_document(document)

    assert len(chunks) == 1
    assert chunks[0].section == "Example"
    assert chunks[0].content == document.content


def test_shorter_fence_does_not_close_longer_fence() -> None:
    document = make_document(
        "## Example\n````text\n```\n## Still code\n````\n## Checks\nInspect logs.\n"
    )

    chunks = chunk_document(document)

    assert [chunk.section for chunk in chunks] == [
        "Example",
        "Checks",
    ]
    assert "## Still code" in chunks[0].content


def test_rejects_empty_section_headings() -> None:
    document = make_document("##\nInspect logs.\n")

    with pytest.raises(IngestionError, match="Empty section heading"):
        chunk_document(document)


def test_chunk_line_ranges_match_normalized_document() -> None:
    document = make_document("\ufeff# Example\r\n\r\n## Checks\r\nInspect logs.\r\n")

    chunks = chunk_document(document)

    assert [(chunk.start_line, chunk.end_line) for chunk in chunks] == [
        (1, 2),
        (3, 4),
    ]
    assert chunks[0].content == "# Example\n\n"
    assert chunks[1].content == "## Checks\nInspect logs.\n"


def test_unicode_line_separator_does_not_shift_source_lines() -> None:
    document = make_document(
        "## Checks\nText\u2028still on the same source line.\n## Limits\nDo not retry.\n"
    )

    chunks = chunk_document(document)

    assert chunks[1].start_line == 3
    assert "\u2028" in chunks[0].content
    assert "".join(chunk.content for chunk in chunks) == document.content


def test_preserves_formatting_and_operational_limits() -> None:
    source = (FIXTURES / "formatting.md").read_text(encoding="utf-8")
    document = make_document(source)

    chunks = chunk_document(document)
    combined = "".join(chunk.content for chunk in chunks)

    assert combined == normalize_markdown(source)
    assert "Keep  two spaces" in combined
    assert "    keep_indentation = True" in combined
    assert "Do not automatically retry a payment." in combined
    assert document.content == source


@pytest.mark.parametrize(
    "source",
    [
        "# Example\n\nA short runbook.",
        "# Example\n\nA short runbook.\n",
        "# Example\n\nA short runbook.\n\n",
    ],
)
def test_preserves_trailing_newlines(source: str) -> None:
    chunks = chunk_document(make_document(source))

    assert len(chunks) == 1
    assert chunks[0].content == source


def test_heading_at_first_line_does_not_create_empty_preamble() -> None:
    document = make_document("## Checks\nInspect logs.\n")

    chunks = chunk_document(document)

    assert len(chunks) == 1
    assert chunks[0].section == "Checks"


def test_blank_preamble_is_attached_to_first_section() -> None:
    source = "\n\n## Checks\nInspect logs.\n"

    chunks = chunk_document(make_document(source))

    assert len(chunks) == 1
    assert chunks[0].section == "Checks"
    assert chunks[0].start_line == 1
    assert chunks[0].content == source


def test_removes_optional_closing_markers_from_section_label() -> None:
    document = make_document("## Checks ##\nInspect logs.\n")

    chunk = chunk_document(document)[0]

    assert chunk.section == "Checks"
    assert chunk.content.startswith("## Checks ##\n")


def test_rejects_oversized_sections() -> None:
    document = make_document("## Checks\n" + "x" * MAX_SECTION_CHARACTERS)

    with pytest.raises(IngestionError, match="exceeds"):
        chunk_document(document)


def test_rejects_content_empty_after_normalization() -> None:
    document = make_document("\ufeff \r\n")

    with pytest.raises(IngestionError, match="no usable content"):
        chunk_document(document)


def test_chunk_ids_are_reproducible() -> None:
    document = make_document("# Example\n\n## Checks\nInspect logs.\n")

    assert chunk_document(document) == chunk_document(document)


def test_content_change_changes_chunk_ids() -> None:
    before = make_document("## Checks\nInspect logs.\n")
    after = make_document("## Checks\nInspect logs and metrics.\n")

    assert chunk_document(before)[0].id != chunk_document(after)[0].id


def test_scope_change_changes_chunk_ids() -> None:
    content = "## Checks\nInspect logs.\n"
    local = make_document(content, environment="local")
    production = make_document(content, environment="production")

    assert chunk_document(local)[0].id != chunk_document(production)[0].id


def test_chunks_preserve_document_provenance() -> None:
    document = make_document("## Checks\nInspect logs.\n")

    chunk = chunk_document(document)[0]

    assert chunk.document == document.metadata
    assert chunk.document_sha256 == document.content_sha256
    assert chunk.ingestion_version == "markdown-it-sections-v1"


def test_ingestion_excludes_drafts_by_default() -> None:
    draft = make_document("## Checks\nInspect logs.\n")

    assert ingest_corpus((draft,)) == ()


def test_preview_can_include_drafts() -> None:
    draft = make_document("## Checks\nInspect logs.\n")

    chunks = ingest_corpus((draft,), include_drafts=True)

    assert len(chunks) == 1
    assert chunks[0].document.status == "draft"


def test_ingestion_includes_approved_documents() -> None:
    approved = make_document(
        "## Checks\nInspect logs.\n",
        status="approved",
    )

    assert len(ingest_corpus((approved,))) == 1


def test_ingestion_order_is_reproducible() -> None:
    first = make_document(
        "## Checks\nFirst.\n",
        document_id="first",
        status="approved",
    )
    second = make_document(
        "## Checks\nSecond.\n",
        document_id="second",
        status="approved",
    )

    assert ingest_corpus((first, second)) == ingest_corpus((second, first))


def test_ingestion_rejects_duplicate_document_ids() -> None:
    document = make_document("## Checks\nInspect logs.\n")

    with pytest.raises(IngestionError, match="IDs must be unique"):
        ingest_corpus((document, document), include_drafts=True)


def test_empty_corpus_produces_no_chunks() -> None:
    assert ingest_corpus(()) == ()


def test_repository_runbooks_can_be_prepared_for_preview() -> None:
    documents = load_corpus(PROJECT_ROOT / "runbooks")

    chunks = ingest_corpus(documents, include_drafts=True)

    assert {chunk.document.id for chunk in chunks} == {
        document.metadata.id for document in documents
    }
    assert len({chunk.id for chunk in chunks}) == len(chunks)

    for document in documents:
        document_chunks = [chunk for chunk in chunks if chunk.document.id == document.metadata.id]

        assert "".join(chunk.content for chunk in document_chunks) == normalize_markdown(
            document.content
        )


@pytest.mark.parametrize(
    ("include_drafts", "expected_mode", "expected_chunks"),
    [
        (False, "approved", 0),
        (True, "preview", 2),
    ],
)
def test_cli_outputs_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    include_drafts: bool,
    expected_mode: str,
    expected_chunks: int,
) -> None:
    write_corpus(tmp_path)
    arguments = [
        "ingest_runbooks",
        "--corpus",
        str(tmp_path),
    ]

    if include_drafts:
        arguments.append("--include-drafts")

    monkeypatch.setattr(sys, "argv", arguments)

    cli.main()

    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert captured.err == ""
    assert result["mode"] == expected_mode
    assert result["loaded_documents"] == 1
    assert result["chunk_count"] == expected_chunks
    assert len(result["chunks"]) == expected_chunks


def test_cli_reports_corpus_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_runbooks",
            "--corpus",
            str(tmp_path / "missing"),
        ],
    )

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 1
    assert "Runbook ingestion failed:" in capsys.readouterr().err
