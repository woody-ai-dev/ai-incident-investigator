from typing import Literal

import pytest
from pydantic import ValidationError

from ai_incident_investigator.knowledge.documents import (
    DoclingLocation,
    DocumentBlock,
    KnowledgeDocument,
    KnowledgeMetadata,
    MarkdownLocation,
)
from ai_incident_investigator.knowledge.retrieval_chunks import (
    ChunkingError,
    ChunkingPolicy,
    prepare_corpus_chunks,
    prepare_document_chunks,
)


def make_document(
    content: str = "Inspect service logs before restarting the service.",
    *,
    document_id: str = "example",
    approved: bool = True,
    file: str = "knowledge/example.md",
    kind: Literal["markdown", "text", "code", "table"] = "markdown",
) -> KnowledgeDocument:
    metadata = KnowledgeMetadata(
        id=document_id,
        title="Service checks",
        document_type="runbook",
        service="order-service",
        environment="local",
        owner="test-owner",
        version=1,
        status="approved" if approved else "draft",
        reviewed_by="test-reviewer" if approved else None,
        file=file,
    )
    location: MarkdownLocation | DoclingLocation

    if file.endswith(".md"):
        location = MarkdownLocation(start_line=10, end_line=30)
    else:
        location = DoclingLocation(
            item_ref="#/texts/7",
            pages=(2, 3) if file.endswith(".pdf") else (),
        )

    return KnowledgeDocument(
        metadata=metadata,
        source_sha256="a" * 64,
        extractor="fixture-extractor-v1",
        blocks=(
            DocumentBlock(
                kind=kind,
                section="Checks",
                content=content,
                location=location,
            ),
        ),
        notes=("Synthetic test document.",),
    )


@pytest.mark.parametrize("limit", [True, 63, 6001, 128.0, "128"])
def test_policy_rejects_invalid_or_coerced_character_limits(limit: object) -> None:
    with pytest.raises(ValidationError):
        ChunkingPolicy.model_validate({"max_characters": limit})


def test_plain_text_chunks_preserve_unicode_offsets_and_all_non_whitespace() -> None:
    content = (
        "Первый шаг: проверьте журналы 🚀 и сохраните результаты.\n\n"
        "Second step: compare the current snapshot with recent errors.\n"
        "Последний шаг: зафиксируйте наблюдения; не меняйте конфигурацию.\n\n"
    ) * 4
    document = make_document(content, file="knowledge/example.html", kind="text")

    chunks = prepare_document_chunks(document, policy=ChunkingPolicy(max_characters=96))

    assert len(chunks) > 1
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    covered: set[int] = set()
    previous_end = 0

    for chunk in chunks:
        source = chunk.source
        assert source.block_ordinal == 0
        assert previous_end <= source.start_char < source.end_char <= len(content)
        assert chunk.content == content[source.start_char : source.end_char]
        assert 0 < len(chunk.content) <= 96
        assert chunk.content.strip()
        covered.update(range(source.start_char, source.end_char))
        previous_end = source.end_char

    assert {index for index, char in enumerate(content) if not char.isspace()} <= covered


def test_chunk_identity_is_deterministic_and_carries_document_provenance() -> None:
    document = make_document()

    first = prepare_document_chunks(document)
    second = prepare_document_chunks(document)

    assert first == second
    assert len(first) == 1
    chunk = first[0]
    assert chunk.id.startswith("chunk-")
    assert len(chunk.id) == len("chunk-") + 64
    assert chunk.document == document.metadata
    assert chunk.source_sha256 == document.source_sha256
    assert chunk.extractor == document.extractor
    assert chunk.chunker_version == "retrieval-characters-v1"
    assert chunk.libraries
    assert chunk.policy == ChunkingPolicy()
    assert chunk.section == document.blocks[0].section
    assert chunk.notes == document.notes


@pytest.mark.parametrize("change", ["hash", "metadata", "extractor", "content", "notes"])
def test_identity_changes_when_its_source_or_provenance_changes(change: str) -> None:
    document = make_document()
    original_id = prepare_document_chunks(document)[0].id

    if change == "hash":
        changed = document.model_copy(update={"source_sha256": "b" * 64})
    elif change == "metadata":
        metadata = document.metadata.model_copy(update={"version": 2})
        changed = document.model_copy(update={"metadata": metadata})
    elif change == "extractor":
        changed = document.model_copy(update={"extractor": "fixture-extractor-v2"})
    elif change == "content":
        block = document.blocks[0].model_copy(update={"content": "Different checks."})
        changed = document.model_copy(update={"blocks": (block,)})
    else:
        changed = document.model_copy(update={"notes": ("Changed extraction note.",)})

    assert prepare_document_chunks(changed)[0].id != original_id


def test_policy_is_part_of_identity_even_when_it_does_not_change_boundaries() -> None:
    document = make_document()
    first = prepare_document_chunks(document, policy=ChunkingPolicy(max_characters=128))[0]
    second = prepare_document_chunks(document, policy=ChunkingPolicy(max_characters=256))[0]

    assert first.content == second.content
    assert first.source == second.source
    assert first.id != second.id


def test_corpus_selects_approved_documents_and_sorts_them_by_id() -> None:
    zulu = make_document(document_id="zulu")
    alpha = make_document(document_id="alpha")
    draft = make_document(document_id="draft", approved=False)

    approved = prepare_corpus_chunks((zulu, draft, alpha))
    preview = prepare_corpus_chunks((zulu, draft, alpha), include_drafts=True)

    assert [chunk.document.id for chunk in approved] == ["alpha", "zulu"]
    assert [chunk.document.id for chunk in preview] == ["alpha", "draft", "zulu"]
    assert approved == prepare_corpus_chunks((alpha, draft, zulu))
    assert prepare_corpus_chunks(()) == ()
    assert prepare_corpus_chunks((draft,)) == ()


def test_corpus_rejects_duplicate_document_ids_before_filtering_drafts() -> None:
    approved = make_document()
    draft = make_document(approved=False)

    with pytest.raises(ChunkingError):
        prepare_corpus_chunks((approved, draft))


@pytest.mark.parametrize(
    ("file", "kind"),
    [
        ("knowledge/example.md", "markdown"),
        ("knowledge/example.html", "text"),
        ("knowledge/example.pdf", "text"),
    ],
)
def test_chunks_retain_original_block_location_without_inventing_narrower_locations(
    file: str,
    kind: Literal["markdown", "text"],
) -> None:
    document = make_document("Check the service status. " * 20, file=file, kind=kind)

    chunks = prepare_document_chunks(document, policy=ChunkingPolicy(max_characters=96))

    assert len(chunks) > 1
    assert all(chunk.source.location == document.blocks[0].location for chunk in chunks)


@pytest.mark.parametrize(
    "atomic",
    [
        "```python\n  result = check()\n  print(result)\n```",
        "    result = check()\n    print(result)",
        "| Signal | Meaning |\n| --- | --- |\n| Logs | History |",
    ],
)
def test_small_markdown_code_and_tables_remain_whole(atomic: str) -> None:
    document = make_document(f"Introduction.\n\n{atomic}\n\nFollow-up checks.\n")

    chunks = prepare_document_chunks(document, policy=ChunkingPolicy(max_characters=96))

    assert any(atomic in chunk.content for chunk in chunks)
    assert all(len(chunk.content) <= 96 for chunk in chunks)


@pytest.mark.parametrize(
    "atomic",
    [
        "```python\n" + "    check_service()\n" * 10 + "```\n",
        "    check_service()\n" * 10,
        "| Signal | Meaning |\n| --- | --- |\n" + "| Logs | Historical events |\n" * 10,
    ],
)
def test_oversized_markdown_code_and_tables_fail_instead_of_being_split(atomic: str) -> None:
    with pytest.raises(ChunkingError):
        prepare_document_chunks(make_document(atomic), policy=ChunkingPolicy(max_characters=96))


@pytest.mark.parametrize("kind", ["code", "table"])
def test_docling_code_and_tables_are_atomic_and_preserve_indentation(
    kind: Literal["code", "table"],
) -> None:
    content = "  first line\n    second line\n"
    document = make_document(content, file="knowledge/example.pdf", kind=kind)

    chunks = prepare_document_chunks(document, policy=ChunkingPolicy(max_characters=96))

    assert len(chunks) == 1
    assert chunks[0].content == content
    assert chunks[0].source.start_char == 0
    assert chunks[0].source.end_char == len(content)


@pytest.mark.parametrize("kind", ["code", "table"])
def test_oversized_docling_code_and_tables_fail(kind: Literal["code", "table"]) -> None:
    document = make_document("x" * 97, file="knowledge/example.html", kind=kind)

    with pytest.raises(ChunkingError):
        prepare_document_chunks(document, policy=ChunkingPolicy(max_characters=96))


def test_block_ordinals_distinguish_identical_text_in_different_source_locations() -> None:
    document = make_document()
    second_block = document.blocks[0].model_copy(
        update={"location": MarkdownLocation(start_line=40, end_line=50)}
    )
    document = document.model_copy(update={"blocks": (*document.blocks, second_block)})

    chunks = prepare_document_chunks(document)

    assert len(chunks) == 2
    assert [chunk.source.block_ordinal for chunk in chunks] == [0, 1]
    assert chunks[0].content == chunks[1].content
    assert chunks[0].id != chunks[1].id


def test_whitespace_blocks_are_skipped_without_renumbering_source_blocks() -> None:
    document = make_document(" \n\t ")
    text = document.blocks[0].model_copy(update={"content": "Actual source text."})
    document = document.model_copy(update={"blocks": (*document.blocks, text)})

    chunks = prepare_document_chunks(document)

    assert len(chunks) == 1
    assert chunks[0].ordinal == 0
    assert chunks[0].source.block_ordinal == 1
    assert chunks[0].content == text.content


def test_document_without_usable_text_fails() -> None:
    with pytest.raises(ChunkingError):
        prepare_document_chunks(make_document(" \n\t "))
