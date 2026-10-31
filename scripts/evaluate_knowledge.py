import argparse
import json
import os
from hashlib import sha256
from pathlib import Path

from openai import OpenAI
from pydantic import ValidationError
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from ai_incident_investigator.knowledge.corpus import load_knowledge_corpus
from ai_incident_investigator.knowledge.embeddings import (
    EmbeddingError,
    EmbeddingSpec,
    OpenAIEmbedder,
)
from ai_incident_investigator.knowledge.loader import CorpusError
from ai_incident_investigator.knowledge.retrieval_chunks import (
    DEFAULT_POLICY,
    ChunkingError,
    ChunkingPolicy,
    prepare_corpus_chunks,
)
from ai_incident_investigator.knowledge.retrieval_evaluation import (
    RetrievalDataset,
    RetrievalEvaluationError,
    evaluate_retrieval,
    validate_retrieval_dataset,
)
from ai_incident_investigator.knowledge.vector_index import KnowledgeIndexError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_DATASET_BYTES = 1_000_000


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate an existing knowledge index.")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--include-drafts", action="store_true")
    parser.add_argument("--k", type=int, default=5, choices=range(1, 21))
    parser.add_argument("--max-characters", type=int, default=DEFAULT_POLICY.max_characters)
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    args = parser.parse_args()
    try:
        policy = ChunkingPolicy(max_characters=args.max_characters)
    except ValidationError:
        parser.error("Invalid character budget")

    try:
        path = args.dataset or args.root / "evals/knowledge-retrieval.json"
        with path.open("rb") as source:
            raw = source.read(MAX_DATASET_BYTES + 1)
        if len(raw) > MAX_DATASET_BYTES:
            raise RetrievalEvaluationError("Retrieval dataset is too large")

        dataset = RetrievalDataset.model_validate_json(raw)
        documents = load_knowledge_corpus(args.root, include_drafts=args.include_drafts)
        chunks = prepare_corpus_chunks(documents, include_drafts=args.include_drafts, policy=policy)
        validate_retrieval_dataset(dataset, chunks)

        scopes = {(chunk.document.service, chunk.document.environment) for chunk in chunks}
        needs_search = any((case.service, case.environment) in scopes for case in dataset.cases)
        collection: str | None = None
        spec = EmbeddingSpec()
        total_tokens = 0

        if needs_search:
            from ai_incident_investigator.knowledge.vector_index import QdrantKnowledgeIndex

            api_key = os.getenv("OPENAI_API_KEY", "").strip()
            if not api_key:
                parser.error("OPENAI_API_KEY is required for embedding operations")

            connection = QdrantClient(
                url=args.qdrant_url, api_key=os.getenv("QDRANT_API_KEY") or None, timeout=10
            )
            try:
                with OpenAI(api_key=api_key, timeout=20, max_retries=2) as provider:
                    embedder = OpenAIEmbedder(provider)
                    index = QdrantKnowledgeIndex(connection, embedder)
                    result = evaluate_retrieval(
                        dataset,
                        chunks,
                        search=lambda request: index.search(
                            chunks, request, include_drafts=args.include_drafts
                        ),
                        k=args.k,
                    )
                    collection = index.collection_name(chunks, include_drafts=args.include_drafts)
                    spec = embedder.spec
                    total_tokens = embedder.total_tokens
            finally:
                connection.close()
        else:
            result = evaluate_retrieval(dataset, chunks, search=lambda request: (), k=args.k)

        output = {
            "schema_version": 1,
            "mode": "preview" if args.include_drafts else "approved",
            "dataset_sha256": sha256(raw).hexdigest(),
            "corpus_sha256": sha256(
                json.dumps(sorted(chunk.id for chunk in chunks)).encode("utf-8")
            ).hexdigest(),
            "chunk_count": len(chunks),
            "collection": collection,
            "embedding": spec.model_dump(mode="json"),
            "embedding_fingerprint": spec.fingerprint,
            "chunk_policy": policy.model_dump(mode="json"),
            "embedding_total_tokens": total_tokens,
            "evaluation": result.model_dump(mode="json"),
        }
    except ValidationError:
        parser.exit(status=1, message="Knowledge evaluation failed: invalid dataset\n")
    except (
        OSError,
        CorpusError,
        ChunkingError,
        EmbeddingError,
        KnowledgeIndexError,
        RetrievalEvaluationError,
    ) as exc:
        parser.exit(status=1, message=f"Knowledge evaluation failed: {exc}\n")
    except (ResponseHandlingException, UnexpectedResponse):
        parser.exit(status=1, message="Qdrant request failed; check the service and credentials\n")

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
