# Curated runbook corpus

The repository contains a small local Markdown corpus under `runbooks/`.

This corpus is preparation for retrieval-augmented investigation.
The investigation pipeline does not load or retrieve these documents yet.

## Files and metadata

`catalog.json` explicitly lists corpus documents.

Each entry contains:

- A stable document ID.
- A title.
- An exact service and environment scope.
- An accountable owner.
- A positive integer document version.
- A draft or approved status.
- A reviewer for approved documents.
- A Markdown filename within the corpus directory.

Catalog schema version and document version have separate meanings.

The loader computes SHA-256 from the exact Markdown file bytes.
Line-ending changes therefore change the content hash.

## Review lifecycle

New runbooks start as draft.

Before approval, review the document against implemented behavior,
source semantics, operational limits, and relevant project documentation.

Replace the owner role with the accountable maintainer.
Set status to approved and record reviewed_by only after review.

When changing approved content:

1. Return the document to draft.
2. Clear reviewed_by.
3. Increment its version.
4. Review the updated content.
5. Approve the new version explicitly.

A reviewer field records a review declaration. It does not prove
that the document is correct or enforce an approval workflow.

## Loading and selection

load_corpus() validates every catalog entry, including drafts.
Invalid entries fail the complete load.

approved_runbooks() selects only approved documents matching the
requested service and environment exactly.

There are no wildcard scopes or environment fallbacks.

Documents absent from the catalog are not loaded.

An empty eligible corpus is valid. Draft documents must not be
used as a fallback.

## Evidence boundaries

Runbooks describe recommended checks and interpretation limits.

They are not telemetry evidence and do not prove that an event occurred,
a cause was established, or a recommended action was executed.

Document text must be treated as untrusted context when model
integration is introduced.

Content hashes identify bytes; they do not certify trustworthiness.

## Evaluation preparation

evals/knowledge-retrieval.json records relevance labels for future search.

Positive labels express semantic relevance within the declared scope,
independently of document approval status.

Current tests validate labels and references. They do not run retrieval
or establish Recall@k, ranking quality, or model accuracy.

Existing pipeline and metric-boundary evaluation remain the baseline
for telemetry preservation. Semantic model quality still requires
separate review.

## Checks

Run from the repository root:

    uv run --locked pytest tests/test_knowledge.py
    uv run --locked ruff format --check .
    uv run --locked ruff check .
    uv run --locked mypy
    uv run --locked pytest

No model calls, database, or running services are required for
the corpus tests.