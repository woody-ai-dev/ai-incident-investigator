# UI development and browser checks

Run commands from the repository root unless a section explicitly starts from
`frontend/`. The UI has no model credentials; analysis is configured only in the
backend.

## Investigation UI

The React and TypeScript interface submits requests to the existing FastAPI API. In
Compose, open [the investigation UI](http://127.0.0.1:3000). Generate a timeout using
the [manual order request](demo-operations.md#reproduce-the-timeout-manually), then
investigate `order-service` in the `local` environment with a window covering that
request. The default Last 15 minutes window refreshes on each submission; editing either
date creates a custom window. Inputs use the browser timezone and are converted to UTC
for the API. Stop waiting cancels the browser request; it does not cancel server-side
processing.

For local development, use Node.js 24 and keep the investigator running on port 8000.
Run from the repository root:

```bash
npm --prefix frontend ci
npm --prefix frontend run dev
```

Open [the local development UI](http://127.0.0.1:5173).

The local Vite server proxies `/api/` to `127.0.0.1:8000`; the Compose frontend uses
Nginx to proxy the same path to `investigator:8000`. No browser API key is required. The
interface is a local demo and has no authentication yet.

Service and environment selectors use the explicit demo target list in
`frontend/src/features/investigations/targets.ts`: currently `order-service` and
`local`. This list is frontend configuration, not automatic service discovery. The menus
use Radix Select for keyboard navigation and focus management. One menu can open at a
time. Menus float above the form without changing the positions of its fields. Long
lists scroll inside the menu, whose height is capped at 280 px and the available
viewport height. Escape keeps the selected value. Reduced motion disables animation. The
request status remains visible beside the submit button. Valid submission keeps the
viewport in place; invalid inputs receive an error message and focus. On wide screens,
the form and flow use equal columns and matching card sizes. The last received report
remains visible while a new investigation runs, fails, or is stopped, with an explicit
notice when it belongs to the previous request.

The report node is neutral before a request, gets a blue outline while pending, and
uses a blue fill once a report arrives. Failed or stopped requests leave it neutral;
a received report can still contain failed LLM analysis or missing evidence.
The evidence flow animates while a request is pending. It does not represent real-time
source progress; the API returns the report as a single response. Receiving a report
also plays a brief signal along the paths containing returned evidence, so fast
responses remain visible without delaying the report or pretending that collection is
still running. After that response, counts come from returned evidence. Zero
observations do not establish that a source is disconnected. Actuator snapshots are
displayed separately from historical observations. The UI supports reduced motion.
Hovering over a source highlights its node and connections and shows source context.
Mouse highlighting clears when the pointer leaves, including after a click. Keyboard
focus provides the same source context until focus moves away. On touch screens, tapping
a source button shows its context until focus moves elsewhere.

Findings and hypotheses link to their evidence IDs. Source references are shown as text
because JSONL references and Compose hostnames are not public web links. Logs and model
text are rendered as text. Export JSON saves a versioned envelope with `schema_version:
1`, the original `request`, and its `report`, so service, environment, and the exact
investigation window travel with the evidence. Partial-source failures and failed LLM
analysis retain available evidence.

Run frontend checks from the repository root:

```bash
npm --prefix frontend run format:check
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
```

Validate the Compose frontend proxy using the existing demo:

```bash
uv run --locked python scripts/check_compose_demo.py \
  --investigator-url http://127.0.0.1:3000/api
```

React Router handles `/`, `/investigations`, and `/investigations/:id`. History
components and cancellable read requests live in `frontend/src/features/history/`;
`api/history.ts` validates summaries and snapshots with Zod. History reuses `SelectField`
with optional All entries; options include demo targets, the current result page, and
selected URL values. Its date controls share `FormControls.module.css` with the main
investigation form, including normal font weight. See [saved history behavior and API](persistence.md#browse-history-in-the-ui).

Feature-specific UI pieces, including `SourceFlow`, live in
`frontend/src/features/investigations/`. Form and report styles are kept in separate CSS
modules; shared selectors and branding remain in `frontend/src/components/`.

## Browser end-to-end checks

The local browser suite uses a production build on port 4173 and fixed API responses. It
checks evidence navigation, JSON download, failure recovery, floating menus, and
mouse/keyboard source inspection, history filtering/pagination, saved-link refresh,
invalid/missing reports, unavailable storage recovery, and mobile overflow. The preview does not proxy requests to the
investigator; no backend or API key is required for this suite.

From `frontend/`:

```bash
npx playwright install chromium
npm run check:e2e
npm run test:e2e
npx playwright show-report playwright-report/ui
```

The Compose browser smoke test uses the real Java service, frontend Nginx proxy, and
investigator. It creates a new simulated timeout and requires that exact order's
evidence in the browser report, with LLM analysis disabled.

The default Compose test addresses are `http://127.0.0.1:3000` for the frontend and
`http://127.0.0.1:8081` for Java. Test runners in another network can override them with
`E2E_COMPOSE_URL` and `E2E_ORDERS_URL`.

From the repository root:

```bash
docker compose up --build --wait --wait-timeout 180
npm --prefix frontend run test:e2e:compose
```

The persistence browser check requires the PostgreSQL overlay and verifies a real
saved snapshot through Nginx, list filters, a direct page reload, and that browsing
makes no POST requests:

```bash
docker compose -f compose.yaml -f compose.persistence.yaml up --build --wait --wait-timeout 180
npm --prefix frontend run test:e2e:history
```

Browser traces and failure screenshots are saved under `frontend/test-results/`. HTML
reports are saved under `frontend/playwright-report/`. CI uploads these artifacts for
seven days. These generated directories are excluded from Git.

The opt-in live browser check requires the LLM-enabled backend from the
[optional analysis section](llm-analysis.md#optional-llm-analysis):

```bash
ALLOW_LIVE_LLM=true npm --prefix frontend run test:e2e:live
```

It submits one fresh investigation through the UI and checks telemetry, completed
analysis, citations, and JSON export. The backend SDK may retry one provider request;
Playwright retries are disabled. This billable test is excluded from ordinary CI and
never needs an API key in the frontend. Add `RECORD_DEMO=true` for reading pauses in the
real browser recording. See the
[recording procedure and artifacts](demo.md#opt-in-browser-check-and-recording).
