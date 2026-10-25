import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from ai_incident_investigator.knowledge.corpus import load_knowledge_corpus
from ai_incident_investigator.knowledge.loader import CorpusError
from ai_incident_investigator.knowledge.retrieval_chunks import (
    DEFAULT_POLICY,
    ChunkingError,
    ChunkingPolicy,
    prepare_corpus_chunks,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare local knowledge retrieval chunks.")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--include-drafts", action="store_true", help="Preview draft documents.")
    parser.add_argument("--max-characters", type=int, default=DEFAULT_POLICY.max_characters)
    args = parser.parse_args()

    try:
        policy = ChunkingPolicy(max_characters=args.max_characters)
    except ValidationError:
        parser.error("--max-characters must be between 64 and 6000")

    try:
        documents = load_knowledge_corpus(args.root, include_drafts=args.include_drafts)
        chunks = prepare_corpus_chunks(documents, include_drafts=args.include_drafts, policy=policy)
    except (CorpusError, ChunkingError) as exc:
        parser.exit(status=1, message=f"Knowledge preparation failed: {exc}\n")

    print(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "preview" if args.include_drafts else "approved",
                "policy": policy.model_dump(mode="json"),
                "document_count": len(documents),
                "chunk_count": len(chunks),
                "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
