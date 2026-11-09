# Local knowledge corpus

The local corpus contains Markdown runbooks, an HTML service overview, and a
text-native PDF configuration reference. The HTTP investigation pipeline does not
consume these documents yet. Dense retrieval and cited RAG recommendations are
available through separate CLIs. Reranking and integration into the HTTP investigation workflow are not
implemented.

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
enforce editorial version increments. Document text remains untrusted context in
model requests. Search-time context assembly must retain
relevant interpretation and operational limits; section splitting alone does
not guarantee complete context.

`evals/knowledge-retrieval.json` records document relevance labels. Positive labels
express semantic relevance within a scope independently of approval status.
Static label checks validate labels and references. The retrieval evaluation CLI
below measures Recall@k and reciprocal rank against this small labeled dataset.
These labels do not establish relevance for every chunk of a document. Existing
pipeline and metric-boundary evaluation remain the baseline for telemetry
preservation; generation quality requires separate review.

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

## Retrieval evaluation

Evaluate the already-built current snapshot with the committed query labels:

```bash
uv run --env-file .env --locked --extra ingestion --extra retrieval \
  python scripts/evaluate_knowledge.py --include-drafts --k 5
```

This explicit command can make billable embedding API requests for scoped queries.
It does not build or modify the index. Run the index command first with the same
corpus mode and character budget. All committed positive examples are drafts;
without `--include-drafts`, missing positive documents are an error before any
external client is created. Approval is never changed automatically.

The command prints one JSON report after a complete successful evaluation. It
records dataset/corpus fingerprints, collection, embedding configuration, chunk
policy, token usage, source chunks, per-case metrics, and macro averages. Exit 0
means the evaluation completed; it does not mean a quality threshold was passed.
No quality threshold is configured in this baseline.

`k` is a chunk cutoff from 1 through 20. Labels refer to documents. Recall@k is
the fraction of labeled documents represented in those chunks, counted once per
document. Reciprocal rank is 1 divided by the first relevant chunk's rank, or 0
if no relevant chunk was retrieved. Mean reciprocal rank averages that value over
positive cases. Duplicate chunks of one document do not increase Recall and are
not removed before computing rank.

Cases with no positive labels have null Recall and reciprocal rank and are
excluded from both averages. The report retains their candidates for inspection.
A query for a scope absent from the corpus returns no candidates without a model
call. A same-scope query with no relevant document can return nearest neighbors;
this baseline does not implement calibrated abstention.

The current dataset contains six hand-written queries and three labeled runbooks.
Document labels are coarse: finding any chunk of a relevant document does not
prove that the exact needed passage was found. Scores describe this small dataset,
not general retrieval accuracy or generated-answer quality.

CI tests use supplied rankings and Qdrant Local with deterministic fixture vectors.
They verify formulas and integration without calling a live model. To compare
chunking policies, rebuild each current snapshot and evaluate with matching
`--max-characters` settings. Keep labels and embedding configuration fixed while
changing one parameter. Reranking, hybrid retrieval and generation evaluation
remain separate work.

## Knowledge context assembly

The `context` subcommand searches the current snapshot and assembles whole chunks:

```bash
uv run --env-file .env --locked --extra ingestion --extra retrieval \
  python scripts/search_knowledge.py context --include-drafts \
  --query "payment timeout" --service order-service --environment local \
  --limit 10 --context-max-chunks 3 --context-max-bytes 12000
```

Build the matching index first with the same corpus mode and `--max-characters`.
The command can make a billable query-embedding request. An empty eligible corpus
needs no API key or Qdrant connection and produces an empty scoped context.

`--limit` bounds retrieved candidates, while `--context-max-chunks` bounds selected
chunks. Both accept values from 1 through 20. The context byte budget defaults to
12000 and accepts values from 512 through 24000. These are initial operational
bounds, not empirically optimized retrieval settings or model token limits.

The output's `assembly.context` records scope, approved/preview mode and full source
chunks, including scores, source hashes and extraction provenance. `payload_bytes`
counts the UTF-8 bytes of `KnowledgeContext.to_json()`, including JSON structure
and metadata. The indented CLI report and its diagnostics are outside that budget.
The recommendation CLI below separately caps its complete serialized input,
including telemetry, request, context and instructions. A byte budget is distinct
from a model token limit.

All candidates are checked before selection. Wrong scopes, unapproved documents
outside preview and conflicting content for one chunk ID fail the operation, even
if that candidate would not fit the budget. Equal duplicate chunks retain their
first result and are reported as `duplicate`. Whole candidates that do not fit are
reported as `byte_budget`; candidates after the selected-chunk cap are reported as
`chunk_limit`. A smaller later candidate may still fit after a larger one is omitted.

Selection preserves result order and source text. It does not truncate or merge
chunks, introduce a score threshold, or rerank candidates. Exclusion diagnostics
make the selected input inspectable; they do not establish semantic relevance.
Preview remains explicit and never changes document approval. The existing
retrieval evaluator scores raw search candidates; it does not score the smaller
context after budget selection. Context-level relevance needs separate evaluation.

Document text remains untrusted reference data. Context assembly does not sanitize
prompt injection or turn a runbook into telemetry evidence. The standalone RAG CLI
below consumes this contract; HTTP integration, saved-report citations and their
UI presentation remain subsequent work.

## RAG recommendations from investigation exports

Use the UI's Export JSON action and save the resulting schema-version-1 file as
`data/investigation-report.json`. The CLI accepts this exact `{schema_version,
request, report}` envelope, derives service/environment from its request and uses
only its original evidence and missing-data fields as observation input. Old
generated summary, findings, hypotheses and recommendations are not prompt input.

Build the matching knowledge snapshot first. The committed sample documents are
still drafts, so a demonstration requires explicit preview:

```bash
uv run --env-file .env --locked --extra ingestion --extra retrieval \
  python scripts/search_knowledge.py index --include-drafts

uv run --env-file .env --locked --extra ingestion --extra retrieval \
  python scripts/recommend_knowledge.py \
  --investigation data/investigation-report.json \
  --query "simulated payment timeout" --include-drafts \
  > data/knowledge-recommendations.json
```

This is an explicit billable operation: it can send the query for embedding, then
send original observations and selected document text for recommendation generation.
`LLM_ENABLED` controls the existing API analysis, not this manual CLI operation.
The existing default generation model is retained; `--model` overrides it.
`--query` selects retrieval candidates; generation remains focused on the exported
incident and selected documents.
SDK retries are disabled for this command. No documents are approved automatically.

The index must already exist for the current corpus and chunk policy. The CLI
never builds an index. Approved mode is the default. No eligible documents, or no
whole candidate fitting the context policy, gives `status=skipped` and no generation.
The latter case may still have query-embedding usage. All no-key/no-client cases
are limited to operations that need no search.

Each generated check has separate `knowledge_ids` and `evidence_ids`. At least one
selected knowledge ID is required per check; telemetry references may be empty.
Both namespaces are constrained in the provider schema and validated locally.
Unknown, overlapping and duplicate references are rejected. If the selected
documents are irrelevant, the model may return empty checks with explanatory
limitations. Reference validity does not prove semantic support or safe advice.

The telemetry analyzer and knowledge recommender perform different generation
tasks: the former builds an incident analysis, while the latter proposes checks
from original observations and retrieved guidance. Their prompts share common
evidence-interpretation rules from `llm/prompts.py`; task-specific instructions
remain separate. Using a standalone CLI is an incremental integration choice, not
a requirement to run every RAG analysis through two model calls. The HTTP API,
stored investigation schema and report UI retain their existing contracts.

The final composed prompt is fixed and hashed. Documents, request descriptions
and telemetry are serialized only into the user data message. The 32000-byte application limit
covers that JSON and the static instructions; it is separate from the selected
context budget and from the provider's model-specific token limits.

The CLI prints a separate JSON artifact containing the original export, its SHA,
query, model and prompt SHA, collection, full selected context, recommendations and
usage. It does not rewrite the input or submit checks for execution. Runtime
failures also print an artifact and exit 1, retaining available context and reported
generation usage. Invalid input/configuration exits before a completed artifact.
Skipped and completed runs exit 0; completed can include an explained abstention.

Embedding totals and generation `LLMUsage` remain separate. A failed embedding
operation has unknown tokens (`null`) rather than a fabricated zero. These values
are not a complete billing ledger and are not added to the API Usage dashboard.
Ordinary tests use fixture vectors, Qdrant Local and mocked SDK HTTP responses;
real semantic quality requires explicit runs and review of citation support.

## Offline review of saved recommendations

Review the saved artifact before integrating its advice into an investigation
report. A known chunk ID links to a chunk in the saved artifact. The reviewer
decides whether the cited text supports the proposed action and reason. The
review CLI records these judgments separately from generation and retrieval metrics.

First check that generation succeeded and the artifact has `status=completed`.
The generator can write a JSON artifact even when it exits with a runtime failure.
`skipped` and `failed` artifacts have no completed model output to review and are
rejected by the review command.

```bash
uv run --locked python scripts/review_knowledge.py init \
  --artifact data/knowledge-recommendations.json \
  --output data/knowledge-review.json

# Fill in the reviewer, notes, and verdicts in knowledge-review.json.
uv run --locked python scripts/review_knowledge.py check \
  --artifact data/knowledge-recommendations.json \
  --review data/knowledge-review.json
```

Review needs no API key, Qdrant service, or ingestion/retrieval extras. `init`
creates a new file and never overwrites an existing review or the source artifact.
It initializes every verdict as `not_reviewed`; it does not infer a semantic pass.

Each entry's `check_index` refers to the zero-based position in
`recommendations.checks`. Keep exactly one entry for every generated check. Read
its cited chunks, cited telemetry, incident request, and data gaps when recording
the following verdicts:

| Criterion | What to assess |
| --- | --- |
| `knowledge_support` | Cited documents support the action and its reason, without invented guidance. |
| `evidence_relevance` | The check fits this incident; telemetry citations support its relevance and missing observations are not invented. |
| `temporal_correctness` | Historical checks, current snapshots, metric meanings, and future instrumentation remain distinct. |
| `actionability` | The proposed action is concrete and feasible; unobserved dependencies are conditional and execution is not claimed. |
| `response_appropriateness` | The overall response gives warranted advice or appropriately abstains when the selected guidance is insufficient. |
| `limitations` | Data gaps, document limits, and any unreviewed preview guidance are disclosed accurately. |

The first four criteria apply to every check. The last two apply to the whole
response. A completed result with empty checks is an explained abstention, not an
automatic pass: its two overall verdicts still require review.

Use `pass`, `fail`, or `not_reviewed`. Every assessed check needs explanatory
`notes`; assessed overall criteria need overall `notes`. Any assessment also
requires a nonempty `reviewer`. A `fail` verdict takes priority over remaining
unreviewed criteria. Only explicit passes for every criterion produce
`reviewed_pass`.

`init` exits 0 when the template is created. `check` exits 0 for `reviewed_pass`,
1 for `pending_review` or `reviewed_fail`, and 2 for invalid input, mismatched source
bytes, or an incomplete set of check entries.

The review stores SHA-256 of the exact artifact bytes. Changing its contents,
check order, or even formatting requires a new review. This binds decisions to a
saved version; the reviewer name is recorded metadata, not an authenticated
signature. A reviewed pass applies only to that artifact and the recorded human
assessments. It is not a retrieval benchmark or a production accuracy score.

This step makes citation support and inappropriate advice visible before API/UI
integration. Broader evaluation datasets and automated evaluation can then build
on concrete reviewed examples.

## Recommendation quality baseline

The [baseline cases](../evals/knowledge-recommendations.json) pair fixed queries
with synthetic UI exports in `evals/fixtures/knowledge-recommendations/`. The
case ID is the export filename stem. Each case records the expected generation
status, useful passages by document and section, and questions for the reviewer.
An empty `expected_context` means no passage is labeled useful. The same-scope
TLS case can still have selected chunks.

CI validates the exports against the CLI's input contract. For a live baseline,
use a clean checkout and the same preview index, retrieval settings, and
generation model for all four cases. Start Qdrant as described in
[Dense retrieval with Qdrant](#dense-retrieval-with-qdrant). Indexing, query
embeddings, and generation can incur OpenAI usage.

```bash
mkdir -p data
run_dir="$(mktemp -d data/knowledge-recommendation-baseline.XXXXXX)"
git rev-parse HEAD > "$run_dir/commit.txt"

uv run --env-file .env --locked --extra ingestion --extra retrieval \
  python scripts/search_knowledge.py index --include-drafts --max-characters 2000 \
  > "$run_dir/index.json"
```

Run the following block for each case, setting `case_id` to its ID. Keep each
attempt, including a failure. Use the same values for the options shown and
record any overrides with the run.

```bash
case_id=simulated-payment-timeout
query="$(uv run --locked --no-sync python - "$case_id" <<'PY'
import json
import sys
from pathlib import Path

manifest = Path("evals/knowledge-recommendations.json")
cases = json.loads(manifest.read_text(encoding="utf-8"))["cases"]
print(next(case["query"] for case in cases if case["id"] == sys.argv[1]))
PY
)"
case_dir="$(mktemp -d "$run_dir/$case_id.XXXXXX")"
exit_code=0
uv run --env-file .env --locked --extra ingestion --extra retrieval \
  python scripts/recommend_knowledge.py --include-drafts \
  --investigation "evals/fixtures/knowledge-recommendations/$case_id.json" \
  --query "$query" --model gpt-4.1-mini-2025-04-14 --limit 10 \
  --max-characters 2000 --context-max-chunks 5 --context-max-bytes 12000 \
  > "$case_dir/recommendations.json" 2> "$case_dir/stderr.txt" || exit_code=$?
printf '%s\n' "$exit_code" > "$case_dir/exit-code.txt"
```

For each case, record the technical outcome (`status` and `issue`) and compare
the expected passages with the selected `assembly.context.chunks`. Keep the
original artifact for the selected text, model, prompt SHA, collection, and
separate embedding and generation usage. If there is no artifact, use stderr
and the exit code to record the failure.

For `completed`, save a separate review using the existing rubric. Record the
answers to the case-specific questions in the review notes. Empty `checks`
still require an assessment of the explanation and limitations.

```bash
uv run --locked --no-sync python scripts/review_knowledge.py init \
  --artifact "$case_dir/recommendations.json" --output "$case_dir/review.json"
# Fill in the reviewer, notes, and verdicts before checking.
uv run --locked --no-sync python scripts/review_knowledge.py check \
  --artifact "$case_dir/recommendations.json" --review "$case_dir/review.json"
```

For the expected `skipped` case, compare `issue` with `expected_issue` in the
manifest and check for empty selected context, zero embedding tokens, and null
generation usage. Report it separately from any reviewed abstention.

### Offline passage coverage

Use the saved recommendation artifact to check which labeled passages survived
context assembly. This command reads local files and requires no API key or
Qdrant service.

```bash
uv run --locked --no-sync python scripts/evaluate_knowledge_context.py \
  --case "$case_id" --artifact "$case_dir/recommendations.json" \
  > "$case_dir/context-evaluation.json"
```

The artifact must match the case query and SHA-256 of the exact export bytes.
A label matches when one selected chunk has the specified document ID and
section and contains the labeled phrase. Matching is case-sensitive and
collapses whitespace. Older labels without a phrase match by document and
section.

`passage_coverage` is the fraction of labels matched at least once. Cases with
no labels and failures without any selected or omitted chunks have null coverage.
An expected skip can satisfy the technical expectation with null coverage.
Each scored label lists matching selected chunk IDs. Omitted chunk IDs and reasons
appear separately.

Exit 0 means the artifact was evaluated, including a recorded status mismatch
or incomplete coverage. Exit 2 means the inputs are invalid or mismatched.
Review the recommendations separately using the existing review CLI.

#### Diagnose a missing passage

Save a prepared snapshot alongside the run, using the same corpus checkout,
draft mode, and character policy as the index. For the preview run above:

```bash
uv run --locked --extra ingestion --extra retrieval \
  python scripts/prepare_knowledge.py --include-drafts --max-characters 2000 \
  > "$run_dir/prepared-chunks.json"

uv run --locked --no-sync python scripts/evaluate_knowledge_context.py \
  --case "$case_id" --artifact "$case_dir/recommendations.json" \
  --prepared-chunks "$run_dir/prepared-chunks.json" \
  > "$case_dir/context-evaluation.json"
```

The evaluator checks chunk identities against their content and provenance,
reproduces the artifact's collection name, and resolves all selected and
omitted references within the scope. This works for existing artifacts if the
matching snapshot is available. Each label's `retrieval_diagnosis` has one of
these statuses:

| Status | Meaning |
| --- | --- |
| `selected` | At least one matching chunk entered the model context. |
| `omitted_by_budget` | A matching chunk was returned but omitted for `chunk_limit` or `byte_budget`. |
| `not_retrieved` | The matching chunk exists in scope but none appeared among the returned candidates. |
| `not_in_scoped_snapshot` | No chunk in the scope matches the label, including the required phrase. |

A run without a recorded collection or with a failure before any candidate
was observed has null diagnosis. A duplicate entry alone does not count as a
budget omission. The report records the SHA-256 of the supplied snapshot.

#### Compare chunk sizes offline

Compare two character limits before building another vector index. The command
loads the selected corpus once and applies both policies to those same documents.
All committed documents are drafts, so this example uses explicit preview.

```bash
mkdir -p data
uv run --locked --extra ingestion python scripts/compare_knowledge_chunking.py \
  --include-drafts --reference-max-characters 2000 --candidate-max-characters 512 \
  > data/knowledge-chunking-2000-vs-512.json
```

The report records the source corpus and label dataset fingerprints, chunk counts,
and the IDs of documents whose ordered sections, source ranges, or chunk text
changed. A policy change can change chunk IDs even when all layouts match.

For each baseline case, the report lists which chunks in its service and
environment contain each labeled passage. Coverage is the fraction of labels
with at least one match in the prepared corpus for that policy. Cases without
labels have null coverage. An anchor lost at this stage cannot be retrieved as
a complete phrase from any single chunk.

The comparison performs no embedding, search, or generation. Evaluate ranking
and selected context separately for candidates that change the layout. If a
policy cannot fit a protected block, the command exits 2 without a JSON report.
