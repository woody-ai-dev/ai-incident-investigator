import argparse
import json
import os
from pathlib import Path

from openai import OpenAI
from pydantic import ValidationError
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from ai_incident_investigator.knowledge.corpus import load_knowledge_corpus
from ai_incident_investigator.knowledge.embeddings import EmbeddingError, OpenAIEmbedder
from ai_incident_investigator.knowledge.loader import CorpusError
from ai_incident_investigator.knowledge.retrieval_chunks import (
    DEFAULT_POLICY,
    ChunkingError,
    ChunkingPolicy,
    prepare_corpus_chunks,
)
from ai_incident_investigator.knowledge.vector_index import (
    KnowledgeIndexError,
    QdrantKnowledgeIndex,
    SearchRequest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=PROJECT_ROOT)
    common.add_argument(
        "--include-drafts", action="store_true", help="Use a separate preview index."
    )
    common.add_argument("--max-characters", type=int, default=DEFAULT_POLICY.max_characters)
    common.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    parser = argparse.ArgumentParser(description="Index or search curated knowledge with Qdrant.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("index", parents=[common])
    search = commands.add_parser("search", parents=[common])
    search.add_argument("--query", required=True)
    search.add_argument("--service", required=True)
    search.add_argument("--environment", required=True)
    search.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    try:
        policy = ChunkingPolicy(max_characters=args.max_characters)
        request = (
            SearchRequest(
                text=args.query,
                service=args.service,
                environment=args.environment,
                limit=args.limit,
            )
            if args.command == "search"
            else None
        )
    except ValidationError:
        parser.error("Invalid character budget, query, scope, or result limit")

    try:
        documents = load_knowledge_corpus(args.root, include_drafts=args.include_drafts)
        chunks = prepare_corpus_chunks(documents, include_drafts=args.include_drafts, policy=policy)
        mode = "preview" if args.include_drafts else "approved"
        output: dict[str, object] = {
            "schema_version": 1,
            "mode": mode,
            "chunk_count": len(chunks),
            "collection": None,
            "embedding_total_tokens": 0,
        }
        if request is not None:
            output["hits"] = []
        scoped = request is None or any(
            chunk.document.service == request.service
            and chunk.document.environment == request.environment
            for chunk in chunks
        )
        if chunks and scoped:
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
                    if request is None:
                        output["collection"] = index.build(
                            chunks, include_drafts=args.include_drafts
                        )
                    else:
                        hits = index.search(chunks, request, include_drafts=args.include_drafts)
                        output["hits"] = [hit.model_dump(mode="json") for hit in hits]
                        output["collection"] = index.collection_name(
                            chunks, include_drafts=args.include_drafts
                        )
                    output["embedding_total_tokens"] = embedder.total_tokens
            finally:
                connection.close()
    except (CorpusError, ChunkingError, EmbeddingError, KnowledgeIndexError) as exc:
        parser.exit(status=1, message=f"Knowledge operation failed: {exc}\n")
    except (ResponseHandlingException, UnexpectedResponse):
        parser.exit(status=1, message="Qdrant request failed; check the service and credentials\n")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
