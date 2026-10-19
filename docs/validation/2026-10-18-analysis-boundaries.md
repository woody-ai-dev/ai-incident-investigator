# Analysis boundaries: real-model validation, 2026-10-18

The proposed implementation was tested in an isolated source copy based on
`d815f56`. The main checkout was not modified. Run labels identify uncommitted
candidate versions, not Git commits; source hashes were saved for each version.

## Setup

- Model: `gpt-4.1-mini-2025-04-14`, matching the private local configuration.
- Official Responses API, real requests; SDK retries disabled.
- Synthetic incident requests, JSONL fixtures, recorded metrics and Actuator data.
- No production telemetry, Docker integration, or live source collection was tested.
- Original model analyses were saved before service validation, separately from
  final reports. Invalid analyses were not replaced with invented successful results.
- Semantic judgments were made by Codex with an independent model-assisted review,
  pending human confirmation. No external judge framework was installed.

## Observed results

| Candidate | Real requests | Technical result | Semantic cases passing all four criteria |
| --- | ---: | --- | --- |
| v1: temporal context and point-snapshot guard | 7 | 7 completed; empty case skipped | 2/7 |
| v2: metric catalogue and interpretation limits | 7 | 7 completed; empty case skipped | 2/7 |
| v3: explicit output-field construction rules | 7 | 7 completed; empty case skipped | 7/7 |
| v3: additional numeric/question variants | 6 | 6 completed | 5/6 |

The four criteria are evidence support, causal reasoning, data limitations, and
useful next checks. Technical completion checks structure, references, evidence
preservation and execution, not semantic correctness.

These are small synthetic regression samples. The additional variants reuse the
same fixtures and do not form an independent production benchmark. Single samples
do not establish stable model behavior or production accuracy.

After the live run, the review question for `variant-sparse-last-zero` was
corrected from `last=1` to `last=0` to match its existing evidence. Model inputs
and Python source did not change; historical run artifacts retain the original
question. No new model call was made for this editorial correction.

## Changes prompted by failures

- Added a producer-owned metric catalogue shared by Prometheus collection and the
  input-only evidence context. Existing queries, descriptions and numeric values
  remain unchanged. Unknown IDs and non-metric sources receive no inferred meaning.
- Explicitly separated scrape observations from application/business health and
  evaluation timestamps from actual scrape timestamps.
- Required heap summaries to retain numeric observations without inventing
  stability, normality, memory pressure, leaks or OOM conclusions.
- Applied simulation and causal limits to every generated text field, including
  summaries and recommendation reasons, rather than only hypotheses.
- Added prompt rules against treating collection gaps as findings supported by
  unrelated Actuator IDs. This is not a semantic runtime guarantee.
- Required retained checks to cover the actual incident interval; future
  instrumentation and adjacent observations remain separate.
- Kept the deterministic outside-window Actuator hypothesis guard and its
  evidence-preserving fallback.

## Remaining observed failure

`variant-scrapes-cannot-prove-orders` says:

> indicating successful metric scrapes at those evaluation times

A returned Prometheus evaluation can reuse an earlier sample within lookback.
It does not timestamp a fresh scrape. The same response correctly leaves
continuous order success and business availability unknown, but this timing
claim still fails evidence support and data limitations.

The additional-variant review therefore remains `reviewed_fail`. No assertion of
complete semantic validation or readiness for autonomous remediation is made.
The temporal runtime guard does not detect this free-text semantic error.

## Usage and estimated cost

27 HTTP responses were recorded, all HTTP 200, with zero SDK retries:

- Input: 56,101 tokens; cached input: 0.
- Output: 8,919 tokens.
- Total: 65,020 tokens.
- Estimated standard API cost: **$0.0367108**.

The estimate uses $0.40 / million input tokens and $1.60 / million output tokens
from the [official model pricing](https://developers.openai.com/api/docs/models/gpt-4.1-mini),
checked on 2026-10-18. It is a token-based estimate, not an account billing receipt.

The final prompt SHA-256 for both v3 suites is:

```text
34861f96203dd08b5f4454585647914b50218f2ce1df2ac02480b677edba29e7
```

## Reproduce without model requests

```bash
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy
uv run --locked pytest
uv run --locked python scripts/evaluate_investigations.py
uv run --locked python scripts/evaluate_investigations.py \
  --dataset evals/metric-boundaries.json \
  --output data/metric-boundary-results.json
uv run --locked python scripts/evaluate_investigations.py \
  --dataset evals/evidence-boundaries-variants.json \
  --output data/evidence-boundary-variant-results.json
```

Verification of the prepared implementation: 313 Python tests passed; strict
mypy passed for 58 files; Ruff formatting and linting passed. One pre-existing
AnyIO deprecation warning remains. Offline suites passed 4/4, 4/4, and 6/6.

## Optional real-model repetition

Use the existing [explicit opt-in procedure](../llm-evaluation.md). Each command
makes potentially billable model requests; the additional dataset needs at most
six requests for one repetition:

```bash
uv run --env-file .env --locked python scripts/evaluate_llm.py \
  --allow-live \
  --model gpt-4.1-mini-2025-04-14 \
  --dataset evals/evidence-boundaries-variants.json \
  --repeats 1 \
  --max-calls 6 \
  --output data/llm-evaluation/evidence-boundary-variants.json
```

Preserve both failed and successful outputs and record semantic review separately.
A fresh run can differ from the saved results above.