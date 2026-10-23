import argparse
import json
from pathlib import Path

from ai_incident_investigator.knowledge.ingestion import (
    INGESTION_VERSION,
    IngestionError,
    ingest_corpus,
)
from ai_incident_investigator.knowledge.loader import (
    CorpusError,
    load_corpus,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and prepare local Markdown runbook chunks."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=PROJECT_ROOT / "runbooks",
        help="Directory containing catalog.json and Markdown documents.",
    )
    parser.add_argument(
        "--include-drafts",
        action="store_true",
        help="Include draft documents for preview only.",
    )
    args = parser.parse_args()

    try:
        documents = load_corpus(args.corpus)
        chunks = ingest_corpus(
            documents,
            include_drafts=args.include_drafts,
        )
    except (CorpusError, IngestionError) as exc:
        parser.exit(
            status=1,
            message=f"Runbook ingestion failed: {exc}\n",
        )

    result = {
        "schema_version": 1,
        "ingestion_version": INGESTION_VERSION,
        "mode": "preview" if args.include_drafts else "approved",
        "loaded_documents": len(documents),
        "prepared_documents": len({chunk.document.id for chunk in chunks}),
        "chunk_count": len(chunks),
        "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
    }

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
