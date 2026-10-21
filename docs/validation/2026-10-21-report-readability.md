# Report readability validation — 2026-10-21

This change targets the short report summary and initial report navigation. It does
not change the saved-report format or trim historical summaries.

## Expected behavior

- One or two summary sentences, no more than 60 words.
- One main observation with its telemetry source, followed by essential uncertainty.
- Detailed timestamps, heap values, and secondary observations remain in findings.
- Completed analysis opens Analysis & checks; other statuses open Evidence.
- Current and saved reports keep working evidence references and full JSON exports.

The prompt and the generated `summary` schema description both explain the field's
purpose. Existing evidence and metric interpretation constraints remain in place.
The [official GPT-4.1 prompting guidance](https://developers.openai.com/cookbook/examples/gpt4-1_prompting_guide)
informed the use of explicit field instructions and a consistent short example.

## Real-model checks

Three billable calls used `gpt-4.1-mini-2025-04-14`, with SDK retries disabled and
one allowed attempt per run. The synthetic `evals/report-readability.json` scenario
contains shutdown/startup logs, heap and scrape summaries, incomplete coverage,
and Actuator observations after the incident window. No production telemetry was sent.

| Run | Words | Review | Estimated USD |
| --- | ---: | --- | ---: |
| Initial instructions | 50 | Three sentences; repeated heap values in summary. | 0.0021504 |
| Explicit sentence roles | 31 | Two sentences, but added secondary metrics and unsupported continuous scraping. | 0.0021276 |
| Field description and final instructions | 30 | Summary met the requested presentation criteria. | 0.0024080 |

Total estimated cost: **$0.006686**. Provider-reported usage is retained in each local
run artifact. These estimates are not a reconciliation with the provider invoice.
Failed presentation attempts were preserved, not rewritten.

Final actual summary:

> Service logs record a graceful shutdown followed by a fresh startup within the incident window. The cause of the shutdown and impact on requests remain unknown based on available telemetry.

The final run passed seven technical checks, including word and sentence limits.
Its system-prompt SHA-256 was
`d7fd91e8fd07a61d5c6d1baa15f2bdf31a0b76134f12f537a84270ca73bc38dc`.
Artifacts remain under the Git-ignored `data/llm-evaluation/` directory:
`report-readability-2026-10-21.json`, `report-readability-2026-10-21-v2.json`, and
`report-readability-2026-10-21-v3.json`. The JSON artifacts keep their conservative
`semantic_quality=pending_manual_review` label.

To reproduce one billable run with a fresh output filename:

```bash
uv run --env-file .env --locked python scripts/evaluate_llm.py \
  --allow-live \
  --model gpt-4.1-mini-2025-04-14 \
  --dataset evals/report-readability.json \
  --max-calls 1
```

## Persistence and UI

The final real report was saved to an isolated PostgreSQL 17 database and read back
through the application API. Its complete report matched the live result; usage
totals matched provider-reported tokens. This did not call the model again.

Chromium rendered the captured real response on both the current investigation
and saved investigation pages. Summary, findings, recommended checks, and source
navigation worked. The 390 px layout had no body overflow, and an empty hypothesis
section was absent. This browser review replayed the captured API data; it made no
additional model requests. No existing development database was modified.

Automated checks: 447 Python tests passed with one PostgreSQL-specific SQLite skip;
105 React tests and 19 Chromium browser tests passed. Formatting, Ruff, mypy, ESLint,
TypeScript checks, and the frontend production build passed.

## Limits

Word and sentence checks measure presentation, not factual support. Sentence splitting
is a punctuation-and-whitespace heuristic; abbreviations can require manual review.
The API accepts older long summaries, and the UI displays them in full.

The final summary met the target. The full model response still used imprecise scrape
wording in a finding and recommendation, and suggested adjacent scrape records without
clearly limiting them to adjacent context. These are remaining interpretation issues;
this small readability change is not a general semantic-quality fix or a reliability
benchmark. One accepted synthetic case does not establish consistent behavior on
unseen incidents.
