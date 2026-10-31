from typing import NoReturn, cast

import pytest
from pydantic import ValidationError

from ai_incident_investigator.knowledge.documents import KnowledgeMetadata
from ai_incident_investigator.knowledge.extraction import LocalDocumentExtractor
from ai_incident_investigator.knowledge.retrieval_chunks import (
    RetrievalChunk,
    prepare_document_chunks,
)
from ai_incident_investigator.knowledge.retrieval_evaluation import (
    RetrievalCase,
    RetrievalDataset,
    RetrievalEvaluationError,
    evaluate_retrieval,
    validate_retrieval_dataset,
)
from ai_incident_investigator.knowledge.vector_index import SearchHit, SearchRequest


def make_chunks(
    document_id: str = "alpha", *, service: str = "order-service"
) -> tuple[RetrievalChunk, ...]:
    metadata = KnowledgeMetadata(
        id=document_id,
        title="Service checks",
        document_type="runbook",
        service=service,
        environment="local",
        owner="fixture-owner",
        version=1,
        status="approved",
        reviewed_by="fixture-reviewer",
        file=f"knowledge/{document_id}.md",
    )
    source = b"# Service checks\n\nInspect retained logs.\n\n## Follow-up\n\nCompare request IDs.\n"
    document = LocalDocumentExtractor().extract(metadata, source)
    return prepare_document_chunks(document)


def make_case(
    case_id: str = "example",
    *,
    labels: tuple[str, ...] = ("alpha",),
    service: str = "order-service",
) -> RetrievalCase:
    return RetrievalCase(
        id=case_id,
        query="retained request logs",
        service=service,
        environment="local",
        relevant_document_ids=labels,
    )


def dataset(*cases: RetrievalCase) -> RetrievalDataset:
    return RetrievalDataset(schema_version=1, cases=cases or (make_case(),))


def hits(*chunks: RetrievalChunk) -> tuple[SearchHit, ...]:
    return tuple(SearchHit(chunk=chunk, score=1.0) for chunk in chunks)


def forbidden_search(request: SearchRequest) -> NoReturn:
    raise AssertionError("Invalid input must not invoke search")


def test_recall_counts_documents_once_and_rr_keeps_chunk_ranks() -> None:
    alpha, beta, gamma = make_chunks(), make_chunks("beta"), make_chunks("gamma")
    result = evaluate_retrieval(
        dataset(make_case(labels=("alpha", "gamma"))),
        (*alpha, *beta, *gamma),
        search=lambda request: hits(beta[0], beta[1], alpha[0], alpha[1]),
        k=4,
    )

    case = result.cases[0]
    assert case.recall_at_k == 0.5
    assert case.reciprocal_rank_at_k == pytest.approx(1 / 3)
    assert len(case.hits) == 4
    assert case.eligible_chunk_count == 6
    assert result.k == 4
    assert result.mean_recall_at_k == 0.5
    assert result.mean_reciprocal_rank_at_k == pytest.approx(1 / 3)


def test_macro_averages_include_misses_and_exclude_no_label_cases() -> None:
    alpha, beta, gamma = make_chunks(), make_chunks("beta"), make_chunks("gamma")
    cases = dataset(
        make_case("partial", labels=("alpha", "gamma")),
        make_case("miss"),
        make_case("no-label", labels=()),
    )
    responses = iter((hits(beta[0], alpha[0]), (), hits(beta[0])))
    result = evaluate_retrieval(
        cases,
        (*alpha, *beta, *gamma),
        search=lambda request: next(responses),
        k=2,
    )

    assert result.positive_cases == 2
    assert result.no_label_cases == 1
    assert result.mean_recall_at_k == pytest.approx(0.25)
    assert result.mean_reciprocal_rank_at_k == pytest.approx(0.25)
    assert result.cases[1].recall_at_k == result.cases[1].reciprocal_rank_at_k == 0.0
    assert result.cases[2].recall_at_k is None
    assert result.cases[2].reciprocal_rank_at_k is None
    assert result.cases[2].hits == hits(beta[0])


def test_no_label_cases_do_not_produce_a_perfect_score() -> None:
    chunks = make_chunks()
    result = evaluate_retrieval(
        dataset(make_case(labels=())),
        chunks,
        search=lambda request: hits(chunks[0]),
    )

    assert result.positive_cases == 0
    assert result.mean_recall_at_k is None
    assert result.mean_reciprocal_rank_at_k is None
    assert len(result.cases[0].hits) == 1


def test_out_of_scope_case_skips_search() -> None:
    result = evaluate_retrieval(
        dataset(make_case(labels=(), service="inventory-service")),
        make_chunks(),
        search=forbidden_search,
    )

    assert result.cases[0].eligible_chunk_count == 0
    assert result.cases[0].hits == ()


def test_empty_corpus_has_no_external_work_for_no_label_cases() -> None:
    result = evaluate_retrieval(
        dataset(make_case(labels=())),
        (),
        search=forbidden_search,
    )
    assert result.cases[0].hits == ()
    assert result.mean_recall_at_k is None


@pytest.mark.parametrize("k", [0, 21, True, 1.5, "5", None])
def test_invalid_k_is_rejected_before_search(k: object) -> None:
    with pytest.raises(RetrievalEvaluationError):
        evaluate_retrieval(dataset(), make_chunks(), search=forbidden_search, k=cast(int, k))


@pytest.mark.parametrize("problem", ["missing", "scope", "duplicate-chunk"])
def test_all_labels_and_chunks_are_validated_before_first_search(problem: str) -> None:
    chunks = make_chunks()
    invalid_case = make_case("bad", labels=("missing",))
    if problem == "scope":
        invalid_case = make_case("bad", service="inventory-service")
    elif problem == "duplicate-chunk":
        invalid_case = make_case("bad")
        chunks = (*chunks, chunks[0])

    with pytest.raises(RetrievalEvaluationError):
        evaluate_retrieval(
            dataset(make_case("valid"), invalid_case), chunks, search=forbidden_search
        )


def test_selected_corpus_must_contain_positive_labels() -> None:
    with pytest.raises(RetrievalEvaluationError, match="include-drafts"):
        validate_retrieval_dataset(dataset(), ())


@pytest.mark.parametrize("problem", ["duplicate", "unknown", "changed", "scope", "too-many"])
def test_untrusted_search_results_cannot_inflate_metrics(problem: str) -> None:
    alpha = make_chunks()
    other_scope = make_chunks("other", service="inventory-service")
    returned = hits(alpha[0], alpha[0])
    if problem == "unknown":
        returned = hits(make_chunks("unknown")[0])
    elif problem == "changed":
        returned = hits(alpha[0].model_copy(update={"section": "Changed after indexing"}))
    elif problem == "scope":
        returned = hits(other_scope[0])
    elif problem == "too-many":
        returned = hits(*alpha, *other_scope)

    with pytest.raises(RetrievalEvaluationError):
        evaluate_retrieval(dataset(), (*alpha, *other_scope), search=lambda request: returned, k=2)


@pytest.mark.parametrize("problem", ["duplicate-case", "duplicate-label", "empty-cases"])
def test_dataset_rejects_ambiguous_ids_and_empty_input(problem: str) -> None:
    case = make_case().model_dump(mode="json")
    cases = [case, case] if problem == "duplicate-case" else [case]
    if problem == "duplicate-label":
        case["relevant_document_ids"] = ["alpha", "alpha"]
    elif problem == "empty-cases":
        cases = []

    with pytest.raises(ValidationError):
        RetrievalDataset.model_validate({"schema_version": 1, "cases": cases})
