# Local knowledge corpus

The local corpus contains Markdown runbooks, an HTML service overview, and a
text-native PDF configuration reference. It prepares future retrieval-augmented
investigation; the investigation pipeline does not consume these documents yet.
Dense retrieval is available through a separate CLI. Reranking and integration
with incident generation are not implemented.

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
uv sync --locked --dev --extra ingestion --extra retrieval
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
Current label checks validate labels and references. They do not run retrieval or
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
uv sync --locked --dev --extra ingestion --extra retrieval
uv run --locked --extra ingestion --extra retrieval ruff format --check .
uv run --locked --extra ingestion --extra retrieval ruff check .
uv run --locked --extra ingestion --extra retrieval mypy
uv run --locked --extra ingestion --extra retrieval pytest
```

To include PostgreSQL tests in the same run, start Docker and use:

```bash
bash scripts/test_with_postgres.sh --with-ingestion --with-retrieval
```

The script creates an isolated database and removes its container afterwards.

CI installs both `ingestion` and `retrieval` extras before full type checking and
tests. Conversion tests block network connections and do not download models.
Without `ingestion`, `document_conversion` tests are skipped; without `retrieval`,
retrieval tests are skipped. Full type checking requires both extras. The API and
Markdown-only workflow retain their base dependencies. Corpus tests do not require
a model key, database, or running service. PostgreSQL tests have their separate
database requirements described in [persistence](persistence.md#test-databases).
Qdrant server tests require `TEST_QDRANT_URL`; the PostgreSQL helper does not start
Qdrant, so those tests are skipped unless a dedicated test instance is provided.

## Retrieval chunk preparation

Run `uv run --locked --extra ingestion python scripts/prepare_knowledge.py` to prepare
approved documents, or add `--include-drafts` for explicit preview. All committed
documents are drafts, so the default output is empty.

The initial policy limits each chunk to 2,000 Python characters. `--max-characters`
accepts values from 64 through 6,000. This is a character budget, not a model token
budget. Prose uses semchunk without overlap; short adjacent extraction blocks are
not merged. Markdown fences, indented code and pipe tables, plus extracted
HTML/PDF code and tables, remain whole. Oversized protected elements fail clearly.

Each chunk retains metadata, the original source hash, extractor and chunker
versions, library versions, policy, extraction notes, and its original block
location. Character offsets `[start_char, end_char)` refer to extracted block text,
not original PDF bytes or HTML source. Markdown locations still identify the whole
source block; they are not narrowed to invented subchunk line ranges. Splitter
whitespace between prose fragments can be omitted; each returned fragment remains
an exact source slice.

Chunk IDs include content, metadata, policy, provenance and processing versions.
Changing these inputs changes the identity. Preview output remains draft context.
Embedding input assembly must enforce its selected model's token budget, including
any added titles or prefixes. Retrieval quality and chunk-size tuning require
subsequent evaluation.

## Dense retrieval with Qdrant

Install the ingestion and retrieval extras for full checks. Qdrant stores derived
vectors and filter metadata; original files remain the source of document text.
The incident API does not call this retrieval code yet.

Start only Qdrant with the knowledge Compose overlay:

```bash
docker compose -f compose.yaml -f compose.knowledge.yaml up -d qdrant
```

Index approved documents, or explicitly use the separate preview namespace:

```bash
uv run --locked --extra ingestion --extra retrieval \
  python scripts/search_knowledge.py index

uv run --env-file .env --locked --extra ingestion --extra retrieval \
  python scripts/search_knowledge.py index --include-drafts

uv run --env-file .env --locked --extra ingestion --extra retrieval \
  python scripts/search_knowledge.py search --include-drafts \
  --query "payment timeout" --service order-service --environment local
```

The preview commands need `OPENAI_API_KEY`. They send embedding text (title,
section and content) or the search query to OpenAI and incur embedding API usage.
`LLM_ENABLED` controls incident generation; this explicit CLI operation is separate.
Successful CLI output reports `embedding_total_tokens`; it is not a billing ledger.
Embedding usage is not yet included in the investigation usage dashboard. An empty
eligible corpus requires neither an API key nor a Qdrant connection.

The baseline uses text-embedding-3-small, 1536 dimensions and cosine similarity.
The cl100k_base tokenizer checks the complete embedding input against 8192 tokens.
Inputs are rejected rather than truncated. The tokenizer may fetch its vocabulary
on first use; it does not download model weights. Unit tests inject a token counter
and mocked SDK HTTP transport, so ordinary tests need no OpenAI access or downloads.
The model name is recorded; it is not a separately pinned dated model snapshot.

Each collection name identifies current chunk IDs, embedding configuration and
approved/preview mode. Search recomputes the current corpus and refuses a missing
or incomplete snapshot. Changes, removals and review status changes therefore
require a new index; old collections cannot silently serve a newer corpus. Empty
approved input never falls back to preview. Returned text and citations come from
the current local chunks, while Qdrant supplies scores and chunk references.

This small-corpus implementation re-extracts documents for each CLI invocation.
Use one index builder per snapshot. Completed snapshots are reused without more
embedding calls; failed partial builds can be retried. Old collections are retained
for explicit cleanup, and no active collection is automatically deleted.

The character chunk policy remains an authoring baseline. Retrieval size, overlap,
ranking thresholds and model quality are not optimized by these storage tests.
Nearest neighbors are suggestions, not proof of relevance or telemetry evidence.

CI runs real Qdrant Local tests and a separate Qdrant server contract test, both
with deterministic fixture vectors. These verify index behavior, not semantic
quality. To run the server check locally, point TEST_QDRANT_URL at a dedicated test
instance and run `uv run --locked --extra retrieval pytest -m qdrant_server`.
