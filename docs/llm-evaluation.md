# Reviewing real LLM investigation outputs

The offline suite validates evidence collection. This optional manual runner adds
real model output review on the same four synthetic scenarios. It uses the real
investigation service, local JSONL fixtures, and recorded metrics and Actuator
results. Docker and live telemetry services are not required.

## Scope

- The existing OpenAI analyzer and `Analysis`/`InvestigationReport` contracts are reused.
- All offline baselines must pass before any model request is attempted.
- Evidence and existing data gaps must survive analysis unchanged.
- Missing evidence skips analysis entirely.
- Technical passes remain separate from semantic quality, which is always
  `pending_manual_review` in the generated artifact.
- Normal application settings, Compose, offline evaluation, and CI stay unchanged.

## Prepare without model requests

Run from the repository root:

```bash
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy
uv run --locked pytest
uv run --locked python scripts/evaluate_investigations.py
uv run --locked python scripts/evaluate_llm.py --help
```

The tests use fake analyzers and an inert client. They do not require credentials.
The live runner requires an explicit `--allow-live` flag and a nonblank
`OPENAI_API_KEY` in the process environment. It does not load `.env` itself.

## Run when API usage is intended

The following command makes real, potentially billable API requests. Use a private
`.env` file already excluded from Git. Never put a real key in an example file.
The model identifier below matches the existing project configuration; your
account must have access to it.

```bash
uv run --env-file .env --locked python scripts/evaluate_llm.py \
  --allow-live \
  --model gpt-4.1-mini-2025-04-14 \
  --repeats 1 \
  --max-calls 3 \
  --revision "$(git rev-parse HEAD)" \
  --output data/llm-evaluation/first-run.json
```

For the current dataset, one repetition produces four case results and at most
three model requests: the empty-evidence scenario is skipped. `--max-calls`
bounds analysis attempts, not a monetary amount. SDK retries are disabled. An
adapter may reject an attempt locally before making an HTTP request.

`LLM_ENABLED` controls the application API. This separate manual runner uses
`--allow-live` as its opt-in, even if the application setting is false.

The requested model, prompt SHA-256, dataset/fixture SHA-256, optional code
revision, UTC run timestamp, case duration, reports, checks, and review questions
are retained. Reports include provider-reported token usage and estimated cost when
available. Missing usage or unknown pricing remain unknown; these artifacts are not
a provider invoice reconciliation.

Output defaults to a new UUID-named file under `data/llm-evaluation/` when
`--output` is omitted. Existing files, including datasets and fixtures, are
refused. Each checkpoint replaces the previous one atomically. A controlled
analysis failure retains the evidence-preserving fallback report. Raw invalid
provider responses are not exposed by the existing analyzer and are not saved.

A run interrupted by Ctrl+C keeps the latest completed cases with
`completed=false`. An in-flight attempt may already have reached the provider;
partial artifacts do not measure all billable usage. A failure before the first
checkpoint can leave an empty reserved output file; inspect the error before
starting a new run with a new output path.

An unsuccessful technical run exits with code 1 after writing results. Invalid
CLI arguments exit with code 2. Other local failures report only an exception
class; check the dataset, destination, model, and attempt budget.

## Manual quality review

Use the existing [review rubric](../evals/README.md#future-model-output-review).
Review every completed analysis alongside its evidence and `review_questions`.
Record the review separately so generated artifacts remain unchanged.

| Case / repetition | Evidence support (0-2) | Causal reasoning (0-2) | Data limitations (0-2) | Next checks (0-2) | Notes |
| --- | --- | --- | --- | --- | --- |
| full-evidence-timeout / 1 | | | | | |
| partial-source-outage / 1 | | | | | |
| current-health-only / 1 | | | | | |

The `no-matching-evidence` case is reviewed for correct skipping and preservation
of gaps, rather than assigned a model-output score.

Check these scenario-specific boundaries:

- A simulated payment timeout must remain explicitly simulated. Its underlying
  cause is unknown; the model must not invent an actual payment-provider outage.
- The cumulative HTTP counter is not the count of failures within the incident
  window.
- Current `health=UP` does not establish historical health or successful order
  processing.
- Source outages must remain visible and conclusions must reflect missing data.
- Diagnostic recommendations describe actions for an engineer; the model has not
  executed them.

Keep failed runs and review notes. Once the first run is understood, repeat the
same cases to inspect variability:

```bash
uv run --env-file .env --locked python scripts/evaluate_llm.py \
  --allow-live \
  --model gpt-4.1-mini-2025-04-14 \
  --repeats 3 \
  --max-calls 9 \
  --revision "$(git rev-parse HEAD)" \
  --output data/llm-evaluation/repeated-run.json
```

Compare artifacts only after checking their model, prompt, and dataset hashes.
A Git revision identifies a commit, not uncommitted changes. The small synthetic
dataset is a release check, not a production-accuracy benchmark.

Before the MVP release, also exercise one live investigation through the UI with
fresh telemetry and review the displayed report. This fixture-based runner does
not replace that final integration check.

## Structured review of saved outputs

The offline review CLI records a separate review of an existing
`LiveEvaluationRun` JSON file. It does not call a model, require an API key,
change a prompt, or modify the original evaluation artifact.

Create a template from a saved run, substituting your existing run path:

```bash
uv run --locked python scripts/review_llm.py init \
  --run data/llm-evaluation/first-run.json \
  --output data/llm-reviews/first-run.json
```

The template contains only completed model analyses. Correctly skipped cases
with no evidence remain technical checks, not semantic model assessments.
The template starts with an empty `reviewer` and `not_reviewed` decisions.
The output file must not already exist.

Open the source run and the review side by side. For every completed analysis,
read its summary, findings, hypotheses, recommendations, evidence, data gaps,
and scenario-specific review questions. Set `reviewer` and record all four
criteria, with explanatory `notes` for each case:

| Field | Pass condition |
| --- | --- |
| `evidence_support` | Material claims are supported by the cited observations. |
| `causal_reasoning` | Symptoms, possible causes, and established facts are distinguished. |
| `data_limitations` | Missing data, sampling limits, and snapshot times constrain conclusions. |
| `next_checks` | Checks are concrete, relevant, and are not described as already executed. |

Use `pass` only when the criterion is fully met. Use `fail` for a material problem,
including a partially met criterion; explain which statement needs correction.
Use `not_reviewed` for work that has not been reviewed. These decisions are
separate from the historical 0-2 rubric; there is no automatic score conversion.

Check the saved review without writing either file:

```bash
uv run --locked python scripts/review_llm.py check \
  --run data/llm-evaluation/first-run.json \
  --review data/llm-reviews/first-run.json
```

| Result | Meaning | Exit code |
| --- | --- | --- |
| `reviewed_pass` | All recorded criteria pass and the saved technical run is consistent and successful. | 0 |
| `pending_review` | At least one criterion remains unreviewed. | 1 |
| `reviewed_fail` | At least one criterion was marked failed. | 1 |
| `technical_failure` | The source run is unfinished, technically unsuccessful, or internally inconsistent. | 1 |
| Invalid input | JSON/schema error, source mismatch, or missing/extra/duplicate review cases. | 2 |

A failed criterion takes precedence over an unreviewed one; a technical failure
blocks approval regardless of the recorded semantic decisions.

The review stores SHA-256 of the exact source bytes. Editing or even reformatting
the source requires a new review. The fingerprint binds the review to a specific
artifact; it is not a signature or proof of reviewer identity. Notes must explain
recorded decisions, and a reviewer is required whenever a decision is recorded.

`reviewed_pass` records a reviewer's judgment about these saved outputs. It is
not an automatic semantic validator or a production accuracy score. The original
run keeps its historical `semantic_quality=pending_manual_review` value.
The current source format does not record the complete planned scenario list,
so review validation does not establish full dataset coverage. These files stay
under Git-ignored `data/`; review them separately before publishing any artifacts.

## Recorded integration check

The first real-model session is summarized in the public
[2026-10-16 validation record](validation/2026-10-16.md). It includes failed runs,
reference-validation fixes, final results, and remaining wording concerns.
Its small known dataset was used during prompt refinement and is not a held-out
quality benchmark. Raw local artifacts remain under ignored `data/`; no API key
or request authorization header belongs in published results.
