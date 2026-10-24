import argparse
import json
from pathlib import Path

from ai_incident_investigator.knowledge.corpus import load_knowledge_corpus
from ai_incident_investigator.knowledge.loader import CorpusError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract local Markdown, HTML, and PDF knowledge.")
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT,
        help="Root containing knowledge/catalog.json and imported runbooks.",
    )
    parser.add_argument(
        "--include-drafts",
        action="store_true",
        help="Include draft documents for preview only.",
    )
    args = parser.parse_args()

    try:
        documents = load_knowledge_corpus(args.root, include_drafts=args.include_drafts)
    except CorpusError as exc:
        parser.exit(status=1, message=f"Knowledge ingestion failed: {exc}\n")

    payload = {
        "schema_version": 1,
        "mode": "preview" if args.include_drafts else "approved",
        "document_count": len(documents),
        "block_count": sum(len(document.blocks) for document in documents),
        "documents": [document.model_dump(mode="json") for document in documents],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
