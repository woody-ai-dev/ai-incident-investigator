import json

import pytest
from pydantic import ValidationError

from ai_incident_investigator.knowledge.documents import KnowledgeMetadata
from ai_incident_investigator.knowledge.extraction import LocalDocumentExtractor
from ai_incident_investigator.knowledge.retrieval_chunks import prepare_document_chunks
from ai_incident_investigator.knowledge.retrieval_context import (
    ContextAssembly,
    ContextError,
    ContextPolicy,
    KnowledgeContext,
    assemble_context,
)
from ai_incident_investigator.knowledge.vector_index import SearchHit, SearchRequest


def request(*, limit: int = 5) -> SearchRequest:
    return SearchRequest(
        text="retained incident records", service="order-service", environment="local", limit=limit
    )


def hit(
    document_id: str = "example",
    *,
    content: str = "Inspect retained incident logs.\n",
    approved: bool = True,
    service: str = "order-service",
    environment: str = "local",
    score: float = 0.5,
) -> SearchHit:
    metadata = KnowledgeMetadata(
        id=document_id,
        title="Retained incident checks",
        document_type="runbook",
        file=f"knowledge/{document_id}.md",
        service=service,
        environment=environment,
        owner="fixture-owner",
        version=1,
        status="approved" if approved else "draft",
        reviewed_by="fixture-reviewer" if approved else None,
    )
    document = LocalDocumentExtractor().extract(metadata, content.encode("utf-8"))
    chunks = prepare_document_chunks(document)
    assert len(chunks) == 1
    return SearchHit(chunk=chunks[0], score=score)


def context(*hits: SearchHit) -> KnowledgeContext:
    return KnowledgeContext(
        mode="approved", service="order-service", environment="local", chunks=hits
    )


def test_utf8_budget_includes_full_serialized_metadata_and_has_exact_boundary() -> None:
    candidate = hit(content="Проверьте сохранённые события.\n" * 10)
    expected = context(candidate)
    encoded = expected.to_json().encode("utf-8")

    assert "Проверьте" in expected.to_json()
    assert len(encoded) > len(expected.to_json())
    assert expected.payload_bytes == len(encoded)
    assert len(encoded) > len(candidate.chunk.content.encode("utf-8"))

    exact = assemble_context(request(), (candidate,), policy=ContextPolicy(max_bytes=len(encoded)))

    assert exact.context == expected
    assert exact.payload_bytes == len(encoded)
    assert exact.omitted == ()
    assert json.loads(exact.context.to_json()) == exact.context.model_dump(mode="json")

    smaller = assemble_context(
        request(), (candidate,), policy=ContextPolicy(max_bytes=len(encoded) - 1)
    )

    assert smaller.context.chunks == ()
    assert smaller.omitted[0].reason == "byte_budget"


@pytest.mark.parametrize(
    "content",
    [
        "```python\n    print('preserve indentation')\n```\n",
        "| Signal | Check |\n| --- | --- |\n| timeout | retained logs |\n",
    ],
)
def test_whole_code_and_table_chunks_keep_content_and_provenance(content: str) -> None:
    candidate = hit(content=content)
    result = assemble_context(request(), (candidate,))

    assert result.context.chunks == (candidate,)
    assert result.context.chunks[0].chunk.content == content
    assert result.context.chunks[0].chunk.source == candidate.chunk.source
    assert result.context.chunks[0].chunk.source_sha256 == candidate.chunk.source_sha256


def test_oversized_candidate_is_skipped_and_a_later_smaller_chunk_can_fit() -> None:
    large, small = hit("large", content="x" * 1800), hit("small")
    budget = context(small).payload_bytes
    result = assemble_context(request(), (large, small), policy=ContextPolicy(max_bytes=budget))

    assert result.context.chunks == (small,)
    assert [(item.chunk_id, item.reason) for item in result.omitted] == [
        (large.chunk.id, "byte_budget")
    ]


def test_chunk_limit_and_duplicate_diagnostics_preserve_first_occurrence() -> None:
    first, second = hit("first", score=-0.8), hit("second", score=0.9)
    duplicate = SearchHit(chunk=first.chunk, score=1.0)
    result = assemble_context(
        request(), (first, duplicate, second), policy=ContextPolicy(max_chunks=1)
    )

    assert result.context.chunks == (first,)
    assert [(item.chunk_id, item.reason) for item in result.omitted] == [
        (first.chunk.id, "duplicate"),
        (second.chunk.id, "chunk_limit"),
    ]


def test_selection_adds_no_score_threshold_or_reranking() -> None:
    first, second = hit("first", score=-0.8), hit("second", score=0.9)

    assert assemble_context(request(), (first, second)).context.chunks == (first, second)


def test_preview_is_explicit_and_retains_draft_status() -> None:
    candidate = hit(approved=False)

    with pytest.raises(ContextError):
        assemble_context(request(), (candidate,))

    preview = assemble_context(request(), (candidate,), include_drafts=True)

    assert preview.context.mode == "preview"
    assert preview.context.chunks[0].chunk.document.status == "draft"


@pytest.mark.parametrize("problem", ["service", "environment", "draft", "collision", "count"])
def test_all_candidates_are_checked_before_budget_selection(problem: str) -> None:
    first = hit("first")
    bad = hit("bad", service="inventory-service")
    if problem == "environment":
        bad = hit("bad", environment="production")
    elif problem == "draft":
        bad = hit("bad", approved=False)
    elif problem == "collision":
        bad = SearchHit(chunk=first.chunk.model_copy(update={"section": "Changed"}), score=0.1)
    elif problem == "count":
        bad = hit("second")

    with pytest.raises(ContextError):
        assemble_context(
            request(limit=1 if problem == "count" else 5),
            (first, bad),
            policy=ContextPolicy(max_chunks=1),
        )


def test_empty_context_counts_metadata_and_round_trips() -> None:
    result = assemble_context(request(), (), policy=ContextPolicy(max_bytes=512))

    assert result.context.purpose == "operational_guidance"
    assert result.context.mode == "approved"
    assert result.context.chunks == ()
    assert result.omitted == ()
    assert 0 < result.payload_bytes <= 512
    assert result.payload_bytes == len(result.context.to_json().encode("utf-8"))
    assert KnowledgeContext.model_validate_json(result.context.to_json()) == result.context


@pytest.mark.parametrize(
    "updates",
    [
        {"max_bytes": 511},
        {"max_bytes": 24001},
        {"max_bytes": True},
        {"max_bytes": "12000"},
        {"max_chunks": 0},
        {"max_chunks": 21},
        {"max_chunks": 1.5},
        {"max_chunks": False},
    ],
)
def test_policy_rejects_invalid_limits(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ContextPolicy.model_validate(updates)


@pytest.mark.parametrize("problem", ["draft", "scope", "duplicate"])
def test_manual_context_cannot_bypass_source_invariants(problem: str) -> None:
    candidate = hit(approved=False) if problem == "draft" else hit()
    items = (candidate, candidate) if problem == "duplicate" else (candidate,)

    with pytest.raises(ValidationError):
        KnowledgeContext(
            mode="approved",
            service="inventory-service" if problem == "scope" else "order-service",
            environment="local",
            chunks=items,
        )


@pytest.mark.parametrize("problem", ["byte_count", "byte_budget", "chunk_limit"])
def test_manual_assembly_cannot_bypass_budget_invariants(problem: str) -> None:
    selected = context(hit(), hit("second"))
    policy = (
        ContextPolicy(max_chunks=1)
        if problem == "chunk_limit"
        else ContextPolicy(max_bytes=512 if problem == "byte_budget" else 12000)
    )

    with pytest.raises(ValidationError):
        ContextAssembly(
            context=selected,
            policy=policy,
            payload_bytes=selected.payload_bytes + (1 if problem == "byte_count" else 0),
            omitted=(),
        )
