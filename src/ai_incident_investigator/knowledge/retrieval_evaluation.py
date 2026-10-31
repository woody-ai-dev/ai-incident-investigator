from collections.abc import Callable
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ai_incident_investigator.knowledge.models import Identifier, KnowledgeModel
from ai_incident_investigator.knowledge.retrieval_chunks import RetrievalChunk
from ai_incident_investigator.knowledge.vector_index import SearchHit, SearchRequest

Metric = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
NonNegativeCount = Annotated[int, Field(strict=True, ge=0)]


class RetrievalEvaluationError(ValueError):
    """Evaluation inputs or retrieval results violate the benchmark contract."""


class RetrievalCase(KnowledgeModel):
    id: Identifier
    query: str = Field(min_length=1, max_length=4000)
    service: Identifier
    environment: Identifier
    relevant_document_ids: tuple[Identifier, ...] = Field(max_length=200)

    @model_validator(mode="after")
    def validate_relevant_documents(self) -> Self:
        if len(self.relevant_document_ids) != len(set(self.relevant_document_ids)):
            raise ValueError("Relevant document IDs must be unique")
        return self


class RetrievalDataset(KnowledgeModel):
    schema_version: Literal[1]
    cases: tuple[RetrievalCase, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_case_ids(self) -> Self:
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Retrieval case IDs must be unique")
        return self


class RetrievalCaseResult(KnowledgeModel):
    case: RetrievalCase
    eligible_chunk_count: NonNegativeCount
    hits: tuple[SearchHit, ...]
    recall_at_k: Metric | None
    reciprocal_rank_at_k: Metric | None


class RetrievalEvaluationResult(KnowledgeModel):
    evaluator_version: Literal["document-labels-at-chunk-k-v1"] = "document-labels-at-chunk-k-v1"
    ranking_unit: Literal["chunk"] = "chunk"
    relevance_unit: Literal["document"] = "document"
    k: Annotated[int, Field(strict=True, ge=1, le=20)]
    positive_cases: NonNegativeCount
    no_label_cases: NonNegativeCount
    mean_recall_at_k: Metric | None
    mean_reciprocal_rank_at_k: Metric | None
    cases: tuple[RetrievalCaseResult, ...]


def validate_retrieval_dataset(
    dataset: RetrievalDataset, chunks: tuple[RetrievalChunk, ...]
) -> None:
    """Check all labels before invoking a potentially billable search provider."""
    ids = [chunk.id for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise RetrievalEvaluationError("Evaluation chunk IDs must be unique")

    document_ids = {chunk.document.id for chunk in chunks}
    for case in dataset.cases:
        scoped_ids = {
            chunk.document.id
            for chunk in chunks
            if chunk.document.service == case.service
            and chunk.document.environment == case.environment
        }
        for document_id in case.relevant_document_ids:
            if document_id not in document_ids:
                raise RetrievalEvaluationError(
                    f"Case '{case.id}' requires missing selected document '{document_id}'; "
                    "check the corpus or use --include-drafts for an explicit preview"
                )
            if document_id not in scoped_ids:
                raise RetrievalEvaluationError(
                    f"Case '{case.id}' labels document '{document_id}' outside its scope"
                )


def evaluate_retrieval(
    dataset: RetrievalDataset,
    chunks: tuple[RetrievalChunk, ...],
    *,
    search: Callable[[SearchRequest], tuple[SearchHit, ...]],
    k: int = 5,
) -> RetrievalEvaluationResult:
    """Score document labels at chunk ranks; no-label cases remain unscored."""
    if type(k) is not int or not 1 <= k <= 20:
        raise RetrievalEvaluationError("Evaluation k must be an integer from 1 through 20")
    validate_retrieval_dataset(dataset, chunks)

    results: list[RetrievalCaseResult] = []
    for case in dataset.cases:
        eligible = {
            chunk.id: chunk
            for chunk in chunks
            if chunk.document.service == case.service
            and chunk.document.environment == case.environment
        }
        hits = (
            search(
                SearchRequest(
                    text=case.query,
                    service=case.service,
                    environment=case.environment,
                    limit=k,
                )
            )
            if eligible
            else ()
        )

        hit_ids = [hit.chunk.id for hit in hits]
        if len(hits) > k or len(hit_ids) != len(set(hit_ids)):
            raise RetrievalEvaluationError(
                f"Case '{case.id}' returned too many or duplicate chunks"
            )
        if any(eligible.get(hit.chunk.id) != hit.chunk for hit in hits):
            raise RetrievalEvaluationError(
                f"Case '{case.id}' returned a changed, unknown, or out-of-scope chunk"
            )

        relevant = set(case.relevant_document_ids)
        recall = None
        reciprocal_rank = None
        if relevant:
            returned_documents = {hit.chunk.document.id for hit in hits}
            recall = len(relevant & returned_documents) / len(relevant)
            reciprocal_rank = next(
                (
                    1.0 / rank
                    for rank, hit in enumerate(hits, start=1)
                    if hit.chunk.document.id in relevant
                ),
                0.0,
            )

        results.append(
            RetrievalCaseResult(
                case=case,
                eligible_chunk_count=len(eligible),
                hits=hits,
                recall_at_k=recall,
                reciprocal_rank_at_k=reciprocal_rank,
            )
        )

    recalls = [result.recall_at_k for result in results if result.recall_at_k is not None]
    reciprocal_ranks = [
        result.reciprocal_rank_at_k for result in results if result.reciprocal_rank_at_k is not None
    ]
    return RetrievalEvaluationResult(
        k=k,
        positive_cases=len(recalls),
        no_label_cases=len(results) - len(recalls),
        mean_recall_at_k=sum(recalls) / len(recalls) if recalls else None,
        mean_reciprocal_rank_at_k=(
            sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else None
        ),
        cases=tuple(results),
    )
