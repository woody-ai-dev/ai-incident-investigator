import argparse
import json
from collections import defaultdict
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from ai_incident_investigator.knowledge.corpus import load_knowledge_corpus
from ai_incident_investigator.knowledge.documents import KnowledgeDocument
from ai_incident_investigator.knowledge.loader import CorpusError
from ai_incident_investigator.knowledge.passage_labels import (
    ContextCase,
    ContextDataset,
    case_export_path,
    matching_chunk_ids,
)
from ai_incident_investigator.knowledge.recommendations import InvestigationExport
from ai_incident_investigator.knowledge.retrieval_chunks import (
    DEFAULT_POLICY,
    ChunkingError,
    ChunkingPolicy,
    ChunkSource,
    RetrievalChunk,
    prepare_corpus_chunks,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def chunk_layouts(
    chunks: tuple[RetrievalChunk, ...],
) -> dict[str, list[tuple[str, ChunkSource, str]]]:
    layouts: dict[str, list[tuple[str, ChunkSource, str]]] = defaultdict(list)
    for chunk in chunks:
        layouts[chunk.document.id].append((chunk.section, chunk.source, chunk.content))
    return dict(layouts)


def compare_passages(
    case: ContextCase,
    export: InvestigationExport,
    reference: tuple[RetrievalChunk, ...],
    candidate: tuple[RetrievalChunk, ...],
) -> dict[str, object]:
    request = export.request

    def matches(chunks: tuple[RetrievalChunk, ...]) -> list[list[str]]:
        scoped = tuple(
            chunk
            for chunk in chunks
            if chunk.document.service == request.service
            and chunk.document.environment == request.environment
        )
        return [matching_chunk_ids(label, scoped) for label in case.expected_context]

    reference_matches = matches(reference)
    candidate_matches = matches(candidate)
    passages = [
        {
            **label.model_dump(mode="json"),
            "reference_chunk_ids": reference_ids,
            "candidate_chunk_ids": candidate_ids,
        }
        for label, reference_ids, candidate_ids in zip(
            case.expected_context, reference_matches, candidate_matches, strict=True
        )
    ]
    return {
        "case_id": case.id,
        "service": request.service,
        "environment": request.environment,
        "reference_passage_coverage": (
            sum(bool(ids) for ids in reference_matches) / len(passages) if passages else None
        ),
        "candidate_passage_coverage": (
            sum(bool(ids) for ids in candidate_matches) / len(passages) if passages else None
        ),
        "passages": passages,
    }


def source_fingerprint(documents: tuple[KnowledgeDocument, ...]) -> str:
    sources = [
        {
            "document": document.metadata.model_dump(mode="json"),
            "source_sha256": document.source_sha256,
            "extractor": document.extractor,
        }
        for document in documents
    ]
    raw = json.dumps(sources, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two chunk sizes on the same local corpus."
    )
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--include-drafts", action="store_true")
    parser.add_argument(
        "--reference-max-characters", type=int, default=DEFAULT_POLICY.max_characters
    )
    parser.add_argument("--candidate-max-characters", type=int, required=True)
    args = parser.parse_args()

    try:
        reference_policy = ChunkingPolicy(max_characters=args.reference_max_characters)
        candidate_policy = ChunkingPolicy(max_characters=args.candidate_max_characters)
    except ValidationError:
        parser.error("Character budgets must be between 64 and 6000")
    if reference_policy == candidate_policy:
        parser.error("Reference and candidate character budgets must differ")

    try:
        dataset_path = args.dataset or args.root / "evals/knowledge-recommendations.json"
        dataset_bytes = dataset_path.read_bytes()
        dataset = ContextDataset.model_validate_json(dataset_bytes)
        cases = [
            (
                case,
                InvestigationExport.model_validate_json(
                    case_export_path(dataset_path, case).read_bytes()
                ),
            )
            for case in dataset.cases
        ]
        documents = load_knowledge_corpus(args.root, include_drafts=args.include_drafts)
        if not documents:
            parser.exit(2, "Chunking comparison failed: no eligible knowledge documents.\n")
        reference = prepare_corpus_chunks(
            documents, include_drafts=args.include_drafts, policy=reference_policy
        )
        candidate = prepare_corpus_chunks(
            documents, include_drafts=args.include_drafts, policy=candidate_policy
        )
    except ValidationError:
        parser.exit(2, "Chunking comparison failed: invalid dataset or investigation export.\n")
    except OSError:
        parser.exit(2, "Chunking comparison failed: unable to read a file.\n")
    except (CorpusError, ChunkingError) as exc:
        parser.exit(2, f"Chunking comparison failed: {exc}\n")

    reference_layout = chunk_layouts(reference)
    candidate_layout = chunk_layouts(candidate)
    output = {
        "schema_version": 1,
        "mode": "preview" if args.include_drafts else "approved",
        "source_corpus_sha256": source_fingerprint(documents),
        "dataset_sha256": sha256(dataset_bytes).hexdigest(),
        "reference": {
            "max_characters": reference_policy.max_characters,
            "chunk_count": len(reference),
        },
        "candidate": {
            "max_characters": candidate_policy.max_characters,
            "chunk_count": len(candidate),
        },
        "changed_document_ids": [
            document_id
            for document_id in sorted(reference_layout.keys() | candidate_layout.keys())
            if reference_layout.get(document_id) != candidate_layout.get(document_id)
        ],
        "cases": [compare_passages(case, export, reference, candidate) for case, export in cases],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
