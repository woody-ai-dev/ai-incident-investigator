import argparse
import os
from hashlib import sha256
from pathlib import Path
from typing import Literal

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
from ai_incident_investigator.knowledge.recommendations import (
    MAX_EXPORT_BYTES,
    NO_ELIGIBLE_KNOWLEDGE_ISSUE,
    InvestigationExport,
    KnowledgeRecommendations,
    RecommendationArtifact,
)
from ai_incident_investigator.knowledge.retrieval_chunks import (
    DEFAULT_POLICY,
    ChunkingError,
    ChunkingPolicy,
    prepare_corpus_chunks,
)
from ai_incident_investigator.knowledge.retrieval_context import (
    DEFAULT_CONTEXT_POLICY,
    ContextError,
    ContextPolicy,
    assemble_context,
)
from ai_incident_investigator.knowledge.vector_index import (
    KnowledgeIndexError,
    QdrantKnowledgeIndex,
    SearchRequest,
)
from ai_incident_investigator.llm.knowledge_recommender import (
    PROMPT_SHA256,
    OpenAIKnowledgeRecommender,
    RecommendationError,
    build_input,
)
from ai_incident_investigator.usage.models import LLMUsage

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recommend cited checks for an investigation export."
    )
    parser.add_argument("--investigation", type=Path, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--include-drafts", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-characters", type=int, default=DEFAULT_POLICY.max_characters)
    parser.add_argument("--context-max-bytes", type=int, default=DEFAULT_CONTEXT_POLICY.max_bytes)
    parser.add_argument("--context-max-chunks", type=int, default=DEFAULT_CONTEXT_POLICY.max_chunks)
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4.1-mini-2025-04-14"))
    args = parser.parse_args()
    args.model = args.model.strip()
    if not 1 <= len(args.model) <= 200:
        parser.error("Invalid model name")

    try:
        with args.investigation.open("rb") as source:
            raw = source.read(MAX_EXPORT_BYTES + 1)
        if len(raw) > MAX_EXPORT_BYTES:
            parser.exit(status=1, message="Investigation export is too large\n")
        investigation = InvestigationExport.model_validate_json(raw)
    except (OSError, ValidationError):
        parser.exit(status=1, message="Cannot read a valid investigation export\n")
    try:
        request = SearchRequest(
            text=args.query,
            service=investigation.request.service,
            environment=investigation.request.environment,
            limit=args.limit,
        )
        chunk_policy = ChunkingPolicy(max_characters=args.max_characters)
        context_policy = ContextPolicy(
            max_bytes=args.context_max_bytes, max_chunks=args.context_max_chunks
        )
    except ValidationError:
        parser.error("Invalid knowledge scope, query, result limit, or chunk/context budget")

    mode: Literal["approved", "preview"] = "preview" if args.include_drafts else "approved"
    status: Literal["completed", "skipped", "failed"] = "skipped"
    issue: str | None = NO_ELIGIBLE_KNOWLEDGE_ISSUE
    assembly = assemble_context(
        request, (), policy=context_policy, include_drafts=args.include_drafts
    )
    recommendations: KnowledgeRecommendations | None = None
    generation_usage: LLMUsage | None = None
    embedding_tokens: int | None = 0
    spec = EmbeddingSpec()
    collection: str | None = None
    try:
        documents = load_knowledge_corpus(args.root, include_drafts=args.include_drafts)
        chunks = prepare_corpus_chunks(
            documents, include_drafts=args.include_drafts, policy=chunk_policy
        )
        if {item.id for item in investigation.report.evidence} & {chunk.id for chunk in chunks}:
            parser.exit(
                status=1, message="Investigation evidence IDs overlap knowledge chunk IDs\n"
            )
        scoped = any(
            chunk.document.service == request.service
            and chunk.document.environment == request.environment
            for chunk in chunks
        )
        if scoped:
            # Reject oversized telemetry before the query-embedding operation.
            build_input(investigation, assembly.context)
            api_key = os.getenv("OPENAI_API_KEY", "").strip()
            if not api_key:
                parser.error("OPENAI_API_KEY is required for embedding and generation")
            try:
                connection = QdrantClient(
                    url=args.qdrant_url, api_key=os.getenv("QDRANT_API_KEY") or None, timeout=10
                )
            except ValueError:
                parser.error("Invalid Qdrant URL or client configuration")
            try:
                with OpenAI(
                    api_key=api_key,
                    base_url="https://api.openai.com/v1",
                    timeout=20,
                    max_retries=0,
                ) as provider:
                    embedder = OpenAIEmbedder(provider)
                    spec = embedder.spec
                    index = QdrantKnowledgeIndex(connection, embedder)
                    collection = index.collection_name(chunks, include_drafts=args.include_drafts)
                    try:
                        hits = index.search(chunks, request, include_drafts=args.include_drafts)
                    except EmbeddingError:
                        embedding_tokens = None
                        raise
                    finally:
                        if embedding_tokens is not None:
                            embedding_tokens = embedder.total_tokens
                    assembly = assemble_context(
                        request, hits, policy=context_policy, include_drafts=args.include_drafts
                    )
                    issue = "No whole retrieved chunk fits the selected context policy."
                    if assembly.context.chunks:
                        result = OpenAIKnowledgeRecommender(provider, args.model).recommend(
                            investigation, assembly.context
                        )
                        recommendations = result.recommendations
                        generation_usage = result.usage
                        status = "completed"
                        issue = None
            finally:
                connection.close()
    except RecommendationError as exc:
        status, issue = "failed", str(exc)
        generation_usage = exc.usage
    except (CorpusError, ChunkingError, ContextError, EmbeddingError, KnowledgeIndexError) as exc:
        status, issue = "failed", str(exc)
    except (ResponseHandlingException, UnexpectedResponse):
        status, issue = "failed", "Qdrant request failed; check the service and credentials"

    if status != "completed":
        recommendations = None
    artifact = RecommendationArtifact(
        status=status,
        input_sha256=sha256(raw).hexdigest(),
        query=request.text,
        investigation=investigation,
        mode=mode,
        collection=collection,
        embedding=spec,
        embedding_total_tokens=embedding_tokens,
        model=args.model,
        prompt_sha256=PROMPT_SHA256,
        assembly=assembly,
        recommendations=recommendations,
        generation_usage=generation_usage,
        issue=issue,
    )
    print(artifact.model_dump_json(indent=2))
    if status == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
