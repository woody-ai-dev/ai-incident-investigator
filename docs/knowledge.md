# Local knowledge corpus

The local corpus contains Markdown runbooks, an HTML service overview, and a
text-native PDF configuration reference. It prepares future retrieval-augmented
investigation; the investigation pipeline does not consume these documents yet.
Embeddings, a search index, reranking, and model integration are not implemented.

## Catalogs and review

`runbooks/catalog.json` (schema version 1) lists Markdown runbooks. The general
`knowledge/catalog.json` (schema version 2) lists additional documents and imports
the runbook metadata when `include_runbooks` is true. Imported runbooks retain
their original owner, version, and review status. IDs and source paths must be
unique across the combined catalog.

Documents declare a stable ID, title, exact service/environment scope, owner,
positive integer version, review status, and source filename. General documents
also declare a type: runbook, architecture, configuration, deployment, or
postmortem. General source paths are relative to the repository root; imported
runbook filenames remain relative to `runbooks/` in their original catalog.

New documents start as `draft`. Before approval, review their content against
implemented behavior, source semantics, and operational limits. Replace the owner
role with an accountable maintainer, set `status` to `approved`, and record
`reviewed_by` only after review.

When changing approved content:

1. Return the document to `draft` and clear `reviewed_by`.
2. Increment its document version.
3. Review the updated content and approve it explicitly.

Review metadata records a declaration; it does not establish correctness or
enforce the editorial workflow. Catalog schema and document versions have separate
meanings. SHA-256 identifies original file bytes, not trustworthiness; line-ending
changes therefore change the hash.

## Markdown ingestion

The original `load_corpus()` validates all runbook entries and files, including
drafts. `approved_runbooks()` selects only approved runbooks for an exact service
and environment. There are no wildcard scopes or environment fallbacks.

The Markdown chunker uses `markdown-it-py` with its CommonMark preset. Top-level
level-two headings define boundaries, including ATX (`## Checks`) and Setext
headings. Nested headings in lists or block quotes and headings inside code do
not create independent sections. An unclosed fenced code block continues to the
end of the document. Empty top-level level-two headings are rejected.

Normalization removes a single initial BOM and converts CRLF and CR to LF.
Internal whitespace, indentation, blank lines, and trailing newlines are
preserved. The original document is unchanged. The parser identifies boundaries;
chunk content comes from normalized source lines, without HTML rendering.
Concatenating chunks in ordinal order reconstructs the normalized document.

Each Markdown chunk records document metadata, the original source hash,
ingestion version, section label, ordinal, inclusive source-line range, and
content. Labels may contain inline Markdown. IDs are deterministic for document
metadata, source hash, ingestion version, ordinal, and line range. Source or
metadata changes produce new IDs even if normalized text is equivalent.

Sections larger than 6,000 characters are rejected. This is an initial authoring
limit, not a token budget or an optimized retrieval chunk size.

Prepare approved runbooks or explicitly preview drafts:

```bash
uv run --locked python scripts/ingest_runbooks.py
uv run --locked python scripts/ingest_runbooks.py --include-drafts
```

## HTML and PDF extraction

Install the optional document dependencies:

```bash
uv sync --locked --dev --extra ingestion
```

`load_knowledge_corpus()` validates the combined catalog metadata, then reads and
extracts selected documents. Drafts are excluded unless preview is explicitly
requested. Unlisted files are not read. A selected file that is missing or cannot
be extracted fails the complete call. No selected documents is a valid result.

The Markdown adapter reuses the existing section chunker and its line provenance.
HTML and PDF use Docling and produce intermediate `KnowledgeDocument` blocks;
those blocks are not yet optimized retrieval chunks.

HTML preparation removes `script`, `style`, and `nav` elements. Browser rendering
and local/remote resource fetching are disabled. Docling can normalize HTML
whitespace, including code-block edges; extraction does not guarantee exact source
preservation. Tables are serialized as Markdown without repeating their child
elements.

PDF uses the native, model-free pipeline. OCR, layout models, table models, and
page-image generation are disabled. This mode extracts text from simple
text-native PDFs; it does not reconstruct complex reading order, headings, or
table structure. Images and scanned text are outside this extractor's scope.

Conversion must return a complete success and usable text. Partial conversion is
rejected. Each result retains original metadata, the original file hash, extractor
and library versions, blocks, and extraction limitations.

PDF locations use actual page numbers. HTML locations reference items in the
Docling representation; they are not original DOM anchors. Converted text does
not acquire invented source-line numbers.

Inspect the combined corpus from the repository root:

```bash
uv run --locked --extra ingestion python scripts/ingest_knowledge.py
uv run --locked --extra ingestion python scripts/ingest_knowledge.py --include-drafts
```

The committed sample corpus contains five draft documents: three Markdown
runbooks and the HTML/PDF examples. The default command therefore returns no
documents; preview includes them and marks its output as `mode=preview`. Preview
output must not be treated as an approved search index.

## Evidence and evaluation boundaries

Knowledge documents describe context, recommended checks, and interpretation
limits. They are not telemetry evidence and do not establish the current cause
or prove that a suggested action was executed. A past postmortem is an analogy,
not proof that the current incident has the same cause.

Ingestion does not remove prompt injection, resolve contradictory documents, or
enforce editorial version increments. Document text remains untrusted context
when model integration is introduced. Search-time context assembly must retain
relevant interpretation and operational limits; section splitting alone does
not guarantee complete context.

`evals/knowledge-retrieval.json` records future relevance labels. Positive labels
express semantic relevance within a scope independently of approval status.
Current checks validate labels and references. They do not run retrieval or
establish Recall@k, ranking quality, or model accuracy. Existing pipeline and
metric-boundary evaluation remain the baseline for telemetry preservation;
semantic model quality requires separate review.

## Fixtures and checks

HTML and PDF examples and test fixtures are committed files. Tests read fixed
fixtures under `tests/fixtures/knowledge/`; they do not generate or copy them at
runtime. The PDF fixture has known markers on two pages so tests can check text,
original source hash, and page attribution.

Run the full Python checks, including real offline conversion:

```bash
uv sync --locked --dev --extra ingestion
uv run --locked --extra ingestion ruff format --check .
uv run --locked --extra ingestion ruff check .
uv run --locked --extra ingestion mypy
uv run --locked --extra ingestion pytest
```

To include PostgreSQL tests in the same run, start Docker and use:

```bash
bash scripts/test_with_postgres.sh --with-ingestion
```

The script creates an isolated database and removes its container afterwards.

CI installs the ingestion extra before type checking and tests. Conversion tests
block network connections and do not download models. Without that extra,
`document_conversion` tests are skipped; full type checking requires it. The API
and Markdown-only workflow retain their base dependencies. Corpus tests do not
require a model key, database, or running service. PostgreSQL tests have their
separate database requirements described in [persistence](persistence.md#test-databases).
