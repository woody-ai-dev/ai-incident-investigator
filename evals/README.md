# Offline investigation evaluation

This dataset checks the investigation pipeline using synthetic, fixed inputs.
It checks pipeline contracts, not model accuracy. Real-model checks are run
separately and documented in the [validation record](../docs/validation/2026-10-16.md).

The runner calls the real `investigate()` service and JSONL collector.
Metrics and Actuator are supplied as recorded collector results. No HTTP
requests, model calls, API keys, or running containers are required.

## Run

Run from the repository root:

```bash
uv run --locked python scripts/evaluate_investigations.py
```

The command saves per-check results and full reports to
`data/evaluation-results.json`. It exits with code 1 when a scenario fails.
Dataset and fixture files cannot be selected as the output destination.

The result identifies its scope explicitly:

```json
{
  "mode": "offline_pipeline",
  "semantic_quality": "not_evaluated"
}
```

## Scenarios

| Scenario | Required behavior |
| --- | --- |
| `full-evidence-timeout` | Preserve matching logs, metric context, and later Actuator snapshots. |
| `no-matching-evidence` | Exclude other services, environments, and records outside the window. |
| `partial-source-outage` | Preserve available logs and explain source failures. |
| `current-health-only` | Keep current snapshots without assigning them historical timestamps. |

Fixture references and observations are synthetic. They are not captured
production telemetry. Each scenario contains manual review questions for a
future model-output evaluation.

## Automatic checks

- Report validation uses the existing `InvestigationReport` contract.
- Evidence IDs, service identity, and expected log observations must match.
- Historical log and metric timestamps must fit the investigation window.
- Recorded metric and Actuator observations must remain unchanged.
- Expected data gaps and current-snapshot limitations must remain visible.
- Analysis stays disabled, with empty findings and hypotheses.

These checks do not judge whether a natural-language explanation is correct.
The `review_questions` field is not an automatic scoring rule.

## Future model-output review

Before release, generate actual model outputs for these inputs and review them
alongside the evidence and scenario-specific questions. Keep failed outputs too.
Add case IDs, model names, prompt revisions, and repeated runs to the results.

Use the following rubric for each actual analysis:

| Criterion | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Evidence support | Material invented or contradicted claims. | Some claims need clarification. | Material factual claims are supported by cited evidence. |
| Causal reasoning | Treats a symptom as a proven cause. | Qualifies claims but misses alternatives. | Separates observations, hypotheses, and unknown causes. |
| Data limitations | Ignores gaps or confuses current and historical state. | Acknowledges some limitations. | Accounts for missing data and observation times. |
| Next checks | Irrelevant or claims unperformed actions. | Relevant but vague. | Concrete checks that could distinguish the remaining hypotheses. |

Do not interpret 4/4 offline pipeline passes as 100% LLM accuracy. A separate
real-model review has been recorded; its small synthetic dataset and limited
repetitions do not establish production accuracy or reliability.

The single-case `report-readability.json` dataset exercises a short, source-attributed
summary with synthetic restart logs and metric/Actuator context. Run it with
`scripts/evaluate_investigations.py --dataset evals/report-readability.json` for the
offline baseline. The opt-in live runner also grades generated summary length against
the 60-word and two-sentence presentation limits; source support and preserved
uncertainty require review.

An additional [metric interpretation regression suite](metric-boundaries.md)
covers scrape success versus business failure, heap summaries without baselines,
cumulative counters, and incomplete scrape coverage. Its offline results also
check pipeline contracts rather than natural-language correctness.
