# Pipeline evaluation

These evaluation paths call the core investigation pipeline directly. They do not use
the optional persistence workflow or create PostgreSQL snapshots. Run commands from the
repository root.

## Offline investigation evaluation

Run the synthetic scenario suite:

```bash
uv run --locked python scripts/evaluate_investigations.py
```

The suite calls the real investigation service with fixed log fixtures and recorded
metric and Actuator results. It verifies evidence preservation, service identity,
historical time windows, current snapshot timestamps, and reported data gaps.

Results are saved to `data/evaluation-results.json`. CI runs the suite and uploads the
results as an artifact.

No running services or API keys are required. This suite evaluates pipeline contracts;
LLM semantic quality is explicitly marked as not evaluated.

See [the evaluation dataset and review rubric](../evals/README.md).

An additional [metric interpretation regression suite](../evals/metric-boundaries.md)
covers successful scrapes alongside failed operations, heap summaries without baselines,
cumulative counters, and incomplete scrape coverage:

```bash
uv run --locked python scripts/evaluate_investigations.py \
  --dataset evals/metric-boundaries.json \
  --output data/metric-boundary-results.json
```

CI runs both four-case offline suites and uploads their separate results. These checks
do not evaluate the correctness of LLM explanations. Real model outputs require the
separate opt-in evaluation and recorded quality review.

## Optional live LLM evaluation

The manual runner evaluates real model outputs on the same four recorded scenarios. It
validates all offline baselines before attempting model requests, preserves original
evidence and data gaps, and saves a checkpoint after each case. Artifacts include the
requested model, prompt and dataset fingerprints, optional code revision, durations,
reports, and technical checks.

Live evaluation requires an explicit `--allow-live` flag and API credentials. It runs
separately from ordinary CI, with bounded analysis attempts and SDK retries disabled. An
empty evidence set skips the model. Existing output files are refused; local results
remain under the Git-ignored `data/` directory.

Technical passes do not establish the correctness of the model's explanation. Generated
artifacts remain marked `pending_manual_review`; model quality must be reviewed against
the evidence and the scenario rubric before release.

See [the setup, commands, and review procedure](llm-evaluation.md).

Real-model checks on 2026-10-16 used `gpt-4.1-mini-2025-04-14`. The final recorded run
passed four technical scenarios: three model analyses and one correctly skipped
empty-evidence case. Earlier failed runs informed prompt and evidence-ID validation
fixes. This is a small synthetic integration check, not a production accuracy benchmark.
See the [review, limitations, and verification record](validation/2026-10-16.md).
