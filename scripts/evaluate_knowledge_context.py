import argparse
import json
from hashlib import sha256
from pathlib import Path
from typing import Literal, Self

from pydantic import ValidationError, model_validator

from ai_incident_investigator.knowledge.models import KnowledgeModel
from ai_incident_investigator.knowledge.passage_labels import (
    ContextCase,
    ContextDataset,
    case_export_path,
    matching_chunk_ids,
)
from ai_incident_investigator.knowledge.recommendations import RecommendationArtifact
from ai_incident_investigator.knowledge.retrieval_chunks import ChunkingPolicy, RetrievalChunk
from ai_incident_investigator.knowledge.retrieval_context import NonNegativeInt, OmittedChunk
from ai_incident_investigator.knowledge.vector_index import knowledge_collection_name

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "evals/knowledge-recommendations.json"


class PreparedChunks(KnowledgeModel):
    schema_version: Literal[1]
    mode: Literal["approved", "preview"]
    policy: ChunkingPolicy
    document_count: NonNegativeInt
    chunk_count: NonNegativeInt
    chunks: tuple[RetrievalChunk, ...]

    @model_validator(mode="after")
    def validate_chunks(self) -> Self:
        if self.chunk_count != len(self.chunks):
            raise ValueError("Prepared chunk count does not match the snapshot")
        if any(chunk.policy != self.policy for chunk in self.chunks):
            raise ValueError("Prepared chunks must share the snapshot policy")
        return self


def scoped_snapshot(
    snapshot: PreparedChunks, artifact: RecommendationArtifact
) -> tuple[RetrievalChunk, ...] | None:
    assembly = artifact.assembly
    if artifact.collection is None or assembly is None:
        return None

    collection = knowledge_collection_name(
        snapshot.chunks, artifact.embedding, include_drafts=snapshot.mode == "preview"
    )
    if snapshot.mode != artifact.mode or collection != artifact.collection:
        raise ValueError("Prepared chunks do not match the artifact collection")
    if any(not chunk.has_matching_id() for chunk in snapshot.chunks):
        raise ValueError("Prepared chunk IDs must match their content and provenance")

    context = assembly.context
    chunks = tuple(
        chunk
        for chunk in snapshot.chunks
        if chunk.document.service == context.service
        and chunk.document.environment == context.environment
    )
    by_id = {chunk.id: chunk for chunk in chunks}
    if any(by_id.get(hit.chunk.id) != hit.chunk for hit in context.chunks) or any(
        item.chunk_id not in by_id for item in assembly.omitted
    ):
        raise ValueError("Artifact chunk references do not match the scoped snapshot")
    return chunks


def diagnose_passage(
    selected_ids: list[str],
    eligible_ids: list[str],
    omitted: tuple[OmittedChunk, ...],
) -> dict[str, object]:
    eligible = set(eligible_ids)
    budget_omissions = [
        item.model_dump()
        for item in omitted
        if item.chunk_id in eligible and item.reason != "duplicate"
    ]
    if selected_ids:
        status = "selected"
    elif budget_omissions:
        status = "omitted_by_budget"
    elif eligible_ids:
        status = "not_retrieved"
    else:
        status = "not_in_scoped_snapshot"
    return {"status": status, "eligible_chunk_ids": eligible_ids, "omitted": budget_omissions}


def evaluate_context(
    case: ContextCase, artifact: RecommendationArtifact, snapshot: PreparedChunks | None = None
) -> dict[str, object]:
    assembly = artifact.assembly
    chunks = tuple(hit.chunk for hit in assembly.context.chunks) if assembly is not None else ()
    omitted = assembly.omitted if assembly is not None else ()
    context_observed = artifact.status != "failed" or bool(chunks or omitted)
    eligible = scoped_snapshot(snapshot, artifact) if snapshot is not None else None
    passages: list[dict[str, object]] = []
    matched = 0

    for label in case.expected_context:
        matches = matching_chunk_ids(label, chunks)
        matched += bool(matches)
        passage = {
            **label.model_dump(),
            "selected_chunk_ids": matches if context_observed else None,
        }
        if snapshot is not None:
            passage["retrieval_diagnosis"] = (
                diagnose_passage(matches, matching_chunk_ids(label, eligible), omitted)
                if eligible is not None and context_observed
                else None
            )
        passages.append(passage)

    return {
        "case_id": case.id,
        "status": artifact.status,
        "issue": artifact.issue,
        "expected_status": case.expected_status,
        "expected_issue": case.expected_issue,
        "technical_expectation_met": artifact.status == case.expected_status
        and (case.expected_issue is None or artifact.issue == case.expected_issue),
        "passage_coverage": matched / len(passages) if context_observed and passages else None,
        "passages": passages,
        "omitted": [item.model_dump() for item in omitted],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate selected context in a saved artifact.")
    parser.add_argument("--case", required=True, help="Case ID in the baseline dataset.")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--prepared-chunks", type=Path, help="Snapshot from scripts/prepare_knowledge.py."
    )
    args = parser.parse_args()

    try:
        dataset = ContextDataset.model_validate_json(args.dataset.read_bytes())
        cases = {case.id: case for case in dataset.cases}

        case = cases.get(args.case)
        if case is None:
            parser.exit(2, "Context evaluation failed: unknown case ID.\n")

        export_sha = sha256(case_export_path(args.dataset, case).read_bytes()).hexdigest()
        artifact_bytes = args.artifact.read_bytes()
        artifact = RecommendationArtifact.model_validate_json(artifact_bytes)
        snapshot_bytes = args.prepared_chunks.read_bytes() if args.prepared_chunks else None
        snapshot = (
            PreparedChunks.model_validate_json(snapshot_bytes)
            if snapshot_bytes is not None
            else None
        )
    except ValidationError:
        parser.exit(2, "Context evaluation failed: invalid dataset, artifact or snapshot JSON.\n")
    except OSError:
        parser.exit(2, "Context evaluation failed: unable to read a file.\n")

    if artifact.query != case.query or artifact.input_sha256 != export_sha:
        parser.exit(
            2, "Context evaluation failed: artifact does not match the case export/query.\n"
        )

    try:
        result = evaluate_context(case, artifact, snapshot)
    except ValueError as exc:
        parser.exit(2, f"Context evaluation failed: {exc}\n")
    result["artifact_sha256"] = sha256(artifact_bytes).hexdigest()
    if snapshot_bytes is not None:
        result["prepared_chunks_sha256"] = sha256(snapshot_bytes).hexdigest()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
