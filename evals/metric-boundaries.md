# Metric interpretation regression cases

This suite covers known interpretation risks with new synthetic observations.
It is a regression suite, not a held-out benchmark or a production accuracy claim.
The default four scenarios in `scenarios.json` remain a separate suite.

| Scenario | Supported observations | Unsupported conclusions |
| --- | --- | --- |
| `scrape-success-business-failure` | A simulated timeout was logged; scrape evaluation values were 1; later Actuator endpoints reported their current state. | Continuous uptime, successful orders, historical health from later snapshots, or exclusion of concurrent real faults. |
| `heap-without-baseline` | Recorded heap min/max/last in bytes. | Normal or stable memory pressure, a memory leak, OOM, or the cause of an order failure from the summary alone. |
| `counter-drop-without-raw-series` | Cumulative counter min=0, max=18, last=2. | Exact failures within the window, a confirmed restart, a number of restarts, or attribution to an individual request. |
| `sparse-scrapes-with-failure` | A zero scrape value was observed; the last value was 1; coverage was 2 of 60 expected evaluation points. | Continuous downtime, outage duration, business recovery, or the status of unobserved targets. |

## Offline pipeline check

```bash
uv run --locked python scripts/evaluate_investigations.py \
  --dataset evals/metric-boundaries.json \
  --output data/metric-boundary-results.json
```

Expected technical result: 4/4 scenarios pass and `semantic_quality=not_evaluated`.
The runner validates evidence preservation, identity, time boundaries, and gaps.
Metrics and Actuator results are recorded fixtures; this suite does not query a
live Prometheus server or test metric collection over HTTP.

The shared JSONL fixture contains one timeout at 10:02 UTC. Only the first case
requests a window containing that record. The other windows intentionally have
no matching logs. Keep the record on one physical line: its evidence ID and
reference depend on that line number.

Review questions and expected results are evaluation metadata. The existing
analyzer receives only the request, collected evidence, and collection gaps.

## Optional real-model evaluation

The following command is opt-in and billable. It makes up to four analysis
attempts, with SDK retries disabled. The default three-call budget is too small
because all four metric scenarios contain evidence.

Commit the suite changes before recording a Git revision. A commit identifier
does not identify uncommitted edits; keep that distinction in comparison notes.

```bash
uv run --env-file .env --locked python scripts/evaluate_llm.py \
  --allow-live \
  --dataset evals/metric-boundaries.json \
  --model gpt-4.1-mini-2025-04-14 \
  --repeats 1 \
  --max-calls 4 \
  --revision "$(git rev-parse HEAD)" \
  --output data/llm-evaluation/metric-boundaries-baseline.json
```

Review all returned analyses alongside their evidence and scenario questions:

```bash
uv run --locked python scripts/review_llm.py init \
  --run data/llm-evaluation/metric-boundaries-baseline.json \
  --output data/llm-reviews/metric-boundaries-baseline.json
```

Fill in the reviewer, four decisions, and notes for every case, then run:

```bash
uv run --locked python scripts/review_llm.py check \
  --run data/llm-evaluation/metric-boundaries-baseline.json \
  --review data/llm-reviews/metric-boundaries-baseline.json
```

## Comparison discipline

Preserve the baseline outputs before changing the prompt or analyzer. Run the
same cases with the same model after the change, use a new output path, and
compare rubric decisions and exact claims. Inspect `prompt_sha256` and
`dataset_sha256` in each run. Do not overwrite outputs or repeatedly regenerate
until a preferred answer appears. A single pass does not measure stability.

Once these cases inform prompt changes, they remain regression cases. Reserve
separately curated unseen cases for a later held-out evaluation. CI runs the
offline suites and fake-analyzer tests only; it does not approve model reasoning.