# MVP demo walkthrough

Show one concrete question: **Why did this order fail, what does the telemetry
actually establish, and what should an engineer check next?**

Use synthetic demo telemetry. The timeout is deliberately simulated; do not
present it as a diagnosed production outage or claim that the assistant repaired
anything.

## Recorded demo

https://github.com/user-attachments/assets/97f5b7a0-0500-4a67-9961-c598e60c685a

[Download the edited MP4 with English captions](https://github.com/woody-ai-dev/ai-incident-investigator/releases/download/v0.1.0/mvp-demo.mp4) · **1:22 · 1920×1080 · 25 fps** ·
[caption source](assets/mvp-demo.en.vtt) ·
[edit timeline and provenance](assets/mvp-demo.edit.json).

[Download the full captioned browser recording](https://github.com/woody-ai-dev/ai-incident-investigator/raw/refs/tags/v0.1.0/docs/assets/mvp-demo-full.mp4) · 1:55 ·
[original captions](assets/mvp-demo-full.en.vtt) ·
[unedited browser export](validation/live-ui-2026-10-16.json).

The walkthrough uses a real OpenAI response and a freshly generated synthetic
order failure. Browser actions were automated; telemetry and the model response
were not mocked. It has English captions and no audio track.

The short edit removes setup pauses and repetitive navigation, enlarges browser
regions, and places the finding before its matching log to explain verification.
Retained browser clips play at their original rate. The persistent **Edited
walkthrough / idle time omitted** label distinguishes this from a real-time run.
The full recording preserves the original browser action order and timing.

The opening is a labelled result card: HTTP 504 is asserted by the browser test;
`PAYMENT_TIMEOUT` and the exact order ID come from its captured Java response.
It is not a screenshot of an HTTP client. The export card shows selected original
fields and explicitly notes the omitted fields. The complete request and report
remain in the linked JSON. No model text was corrected or replaced, and editing
did not make another model request.

Captions retain the observed interpretation errors, including the unsupported
heap-stability claim and the limits of scrape availability and cumulative
counters. The final UI review notice was added after the original capture.

## Rehearsal without a model

From the repository root:

```bash
docker compose config --quiet
docker compose up --build --wait --wait-timeout 180
uv sync --locked --dev
uv run --locked python scripts/check_investigation_metrics.py
uv run --locked python scripts/check_investigation_context.py
```

Open `http://127.0.0.1:3000`. Create a fresh timeout immediately before submitting
the UI investigation:

```bash
curl -i http://127.0.0.1:8081/api/v1/orders \
  -H 'Content-Type: application/json' \
  -d '{"productId":"book-1","quantity":2}'
```

Expect HTTP 504, `PAYMENT_TIMEOUT`, and an `orderId`. Save that ID for the
recording. Allow at least one fresh Prometheus scrape (the demo interval is five
seconds). The UI's default **Last 15 minutes** refreshes on submission.
Select `order-service` and `local`; describe the failed order using its ID.

The evidence flow animates while the request is pending and briefly after the
response. It shows pending activity and returned evidence counts, not live
per-source progress. With default Compose, expect `analysis_status=not_requested`:
there is no model explanation to demonstrate in this mode.

## Optional real-model demonstration

This mode makes billable API calls. In the private, Git-ignored `.env` file,
configure `OPENAI_API_KEY` and `OPENAI_MODEL`. Keep the key out of screen captures,
terminal command arguments, repository files, and the browser.

```bash
docker compose -f compose.yaml -f compose.llm.yaml config --quiet
docker compose -f compose.yaml -f compose.llm.yaml up --build --wait --wait-timeout 180
```

Do not print the interpolated Compose configuration; it contains the key. The
backend receives the key through its environment; the frontend does not need it.
Run the manual order request above again, then submit one UI investigation.
The ordinary Compose check scripts deliberately require analysis to be disabled;
do not run them against this enabled instance.

Expect `analysis_status=completed`, then inspect the report before recording:

1. Locate the log for the exact new order ID and its simulation marker.
2. Confirm metric evidence belongs to the selected service and environment.
3. Distinguish cumulative counters from failures during this window.
4. Check Actuator snapshot timestamps and their current-state limitation.
5. Follow each finding's evidence reference. A valid ID alone does not establish
   that the cited observation supports the statement.
6. Verify that missing traces and any collection gaps remain visible.
7. Confirm recommendations describe checks, not actions already performed.
8. Export JSON and verify the original request, report, and analysis status.

An API error or rejected analysis should retain the collected evidence and show
`failed`. Do not edit a model response to make the recording look successful.
Record the actual outcome and any material limitation.

### Opt-in browser check and recording

After starting the LLM-enabled backend above, the separate live browser test can
create a fresh simulated order failure and exercise the real UI and API. Install
the frontend dependencies and Playwright Chromium as described in the README's
browser-check section first.

Choose **one** command from the repository root. For the integration check:

```bash
ALLOW_LIVE_LLM=true npm --prefix frontend run test:e2e:live
```

For the same check with reading pauses for a roughly two-minute recording:

```bash
ALLOW_LIVE_LLM=true RECORD_DEMO=true npm --prefix frontend run test:e2e:live
```

`RECORD_DEMO=true` adds viewing time; it does not replace telemetry or model
responses. Each invocation creates a new incident and submits exactly one UI
investigation. Playwright retries are disabled. The backend SDK can retry one
failed provider request, so one UI submission is not a strict one-HTTP-call
billing limit. The required `ALLOW_LIVE_LLM=true` guard fails before the test
when absent. The API key belongs only to the backend; never pass it to npm or
the browser.

The check requires the created order's timeout log, three metric items, two
Actuator snapshots, completed analysis, retained data gaps, working citation
navigation, and an exported JSON envelope matching the request and report. It
also checks for duplicate submissions and browser errors. These are integration
assertions; the test does not grade whether every model conclusion is supported.

Videos, screenshots, and JSON captures are saved under
`frontend/test-results/live/`, and the HTML report is under
`frontend/playwright-report/live/`. Both directories are Git-ignored. Review the
actual report before sharing a selected recording. Ordinary UI/Compose suites
and CI do not run this billable test.


After the live demo, return to the no-key configuration:

```bash
docker compose up --wait --wait-timeout 180
```

This recreates the investigator with `LLM_ENABLED=false`. It does not revoke the
key in the private `.env` file. Stop services with `docker compose down` when done;
volumes retain local demo telemetry unless explicitly removed.

## Published 82-second edit

| Time | Screen | Purpose |
| --- | --- | --- |
| 0:00–0:06 | Captured synthetic 504, error code and order ID | Establish the concrete incident. |
| 0:06–0:13 | Service, environment, window and submission | Show the investigation scope. |
| 0:13–0:20 | Original evidence-flow animation | Explain activity and returned counts without implying per-source progress. |
| 0:20–0:28 | Actual summary and labelled quotation | Show a real response that needs verification. |
| 0:28–0:35 | Original finding and `log-28` citation | Connect the conclusion to its observation. |
| 0:35–0:43 | Enlarged log and exact source/time | Match the timeout to the failed order. |
| 0:43–0:49 | Original heap claim and missing context | Keep the model's unsupported interpretation visible. |
| 0:49–0:57 | Availability, heap and counter caveats | Distinguish observations from stronger claims. |
| 0:57–1:04 | Original Data gaps tab | Show missing traces and current-only Actuator context. |
| 1:04–1:16 | Labelled excerpt from the actual JSON export | Show retained request/report fields; full export is linked. |
| 1:16–1:22 | Project name, repository and Docker demo | Give viewers a concrete next step. |

Use English captions or narration for an international portfolio. Keep terminal
output limited to the synthetic order request; do not open `.env`, provider
settings, shell environment dumps, or container inspection output on screen.
When editing, remove idle time and repetitive navigation, label excerpts and
reordered sequences, and preserve the full capture. If the demo is accelerated or
uses a replay, label it so viewers can distinguish it from real-time collection.

The [validation record](validation/2026-10-16.md) distinguishes automated checks,
real-model review, and maintainer sign-off. A demo video does not replace those
checks.
