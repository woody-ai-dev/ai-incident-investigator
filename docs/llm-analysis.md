# Optional model analysis

Model calls are explicitly opt-in. For the offline container demo, follow the [quick
start](../README.md#quick-start-with-docker-compose).

## Optional LLM analysis

Live analysis is optional. The default Compose demo and CI do not use it.

For local live analysis, create a private .env file using .env.example as a template.
Update an existing .env instead of overwriting it.

```dotenv
INVESTIGATOR_LOG_PATH=data/order-service-timeout.jsonl
LLM_ENABLED=true
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=gpt-4.1-mini-2025-04-14
```

Replace the key placeholder with your own API key. Keep real credentials out of
.env.example and Git.

Restart the local investigator with:

```bash
uv run --env-file .env --locked uvicorn ai_incident_investigator.main:app --reload
```

Python settings read process environment variables. They do not automatically load .env;
the command above loads it through uv.

To enable real analysis in the container demo, keep `OPENAI_API_KEY` and `OPENAI_MODEL`
in a private `.env` file and use the explicit override:

```bash
docker compose -f compose.yaml -f compose.llm.yaml config --quiet
docker compose -f compose.yaml -f compose.llm.yaml up --build --wait --wait-timeout 180
```

This passes the key only to the backend container. Model requests can incur API charges.
The default `compose.yaml` remains usable without a key. Avoid printing the fully
interpolated Compose configuration because it contains the key. See the [live demo
steps](demo.md#optional-real-model-demonstration).

When analysis is enabled, a missing or blank key prevents application startup. Requests
send the investigation request, collected log, metric, and Actuator evidence, and data
gaps to the configured model.

| analysis_status | Meaning |
| --- | --- |
| not_requested | LLM analysis is disabled. |
| skipped | Analysis is enabled, but no evidence was collected from the configured sources. |
| completed | Analysis passed output, evidence-reference, and temporal-support validation. |
| failed | Analysis failed or was rejected; evidence has been retained. |

Findings and hypotheses must reference existing evidence IDs. The analyzer binds all
reference fields to those IDs in the model response schema and validates them locally.
This checks report structure and references, not the correctness of the reasoning.
Current Actuator snapshots can remain available when no historical logs or metrics
match. Such snapshots still count as collected evidence; their time limitations
accompany them in the analysis input.

Input-only temporal metadata describes each observation relative to the incident window.
The service rejects a hypothesis supported only by Actuator point snapshots outside that
window and retains the evidence in a fallback report. Passing this narrow rule does not
establish that the reasoning is correct. See [analysis evidence
boundaries](analysis-boundaries.md).

Known Prometheus observations also carry input-only metric interpretation metadata from
a shared producer catalogue. It distinguishes scrape observations, heap summaries, and
cumulative counters without inferring meaning from free text. The [real-model validation
record](validation/2026-10-18-analysis-boundaries.md) includes the observed improvements
and a remaining scrape-timing error.
