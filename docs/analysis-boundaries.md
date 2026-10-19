# Analysis evidence boundaries

The analyzer receives the original evidence and input-only `evidence_context`
metadata. Metadata joins each observation by `evidence_id`; it is not another
source of evidence and does not change the public report schema.

`point_observation` describes a timestamp. `interval_observation` describes a
half-open interval. The requested incident window also uses `[start, end)`.

| `time_scope` | Meaning |
| --- | --- |
| `before_window` | The observation precedes the incident window. |
| `within_window` | The point or entire interval is contained in the window. |
| `overlaps_window` | An interval intersects the window without being fully contained. |
| `after_window` | The observation starts at or after the excluded window end. |

Scope comes from validated timestamps, not words in a summary. Temporal inclusion
does not establish causality.

Known Prometheus evidence also receives typed `metric_interpretation` metadata:
the metric kind, supported observation, and interpretation limitations. The
producer and analyzer share a catalogue defining the three reserved metric IDs,
descriptions, and meanings. Only metric-source evidence with an exact registered
ID receives this metadata. Unknown metric IDs receive no inferred interpretation;
summary keywords and reference URLs are never parsed to guess metric meaning.
Future collectors must preserve those reserved meanings or define a new catalogue
entry. Public evidence and report fields remain unchanged.

After normal report and reference validation, the service rejects an analysis
if any hypothesis is positively supported only by Actuator point snapshots
outside the incident window. Contradicting references do not count as positive
support. An accurate finding about a later snapshot remains allowed.

Rejection returns `analysis_status=failed`, keeps the original evidence and
collection gaps, and uses the existing fallback summary and recommended checks.
The complete generated analysis is discarded; individual claims are not silently
removed. The original provider request, if made, can still incur charges.

This is one deterministic rule. It does not prove that accepted hypotheses are
correct, detect irrelevant additional supporting references, or validate the
meaning of summaries, findings, and recommendations. Interval-valued Actuator
observations need an explicit future policy; the current collector emits points.

## Verification

```bash
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy
uv run --locked pytest
uv run --locked python scripts/evaluate_investigations.py
uv run --locked python scripts/evaluate_investigations.py \
  --dataset evals/metric-boundaries.json \
  --output data/metric-boundary-results.json
```

These checks use synthetic evidence and fake analyzers; they do not call a model.
A repeatable, opt-in real-model comparison uses the existing
[LLM evaluation procedure](llm-evaluation.md) and recorded semantic review.
An analysis rejected by this rule is an expected application fallback but is not
a successful model-quality result. Preserve that failure in evaluation artifacts.

DeepEval G-Eval or Ragas custom criteria can later add model-based semantic
scoring of saved outputs. Keep judge runs separate from ordinary CI, record their
configuration and results, and calibrate them against reviewed examples.