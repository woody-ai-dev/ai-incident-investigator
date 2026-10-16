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
are retained. Token usage and monetary cost are not measured by this version;
the current analyzer interface returns only `Analysis`.

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

## Recorded integration check

The first real-model session is summarized in the public
[2026-10-16 validation record](validation/2026-10-16.md). It includes failed runs,
reference-validation fixes, final results, and remaining wording concerns.
Its small known dataset was used during prompt refinement and is not a held-out
quality benchmark. Raw local artifacts remain under ignored `data/`; no API key
or request authorization header belongs in published results.
