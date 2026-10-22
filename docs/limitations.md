# Current implementation limits

These limits describe the current implementation. Engineering review of model
conclusions is required; a technically valid response is not a verified root cause.

## Current limits

The real UI check found unsupported model interpretations of scrape availability and
heap stability. A completed report means the response passed structural and reference
validation, not that its conclusions are verified. The UI displays a review notice;
original evidence is available for checking each claim. See the
[recorded quality findings](validation/2026-10-16.md#fresh-ui-investigation).


- Investigations run on request and collect one local JSONL source, optional Prometheus data,
  and optional current context from one configured Actuator target.
- There is no continuous incident detection or service discovery.
- Log collection allows at most 100 records, 5 MiB scanned, and 64 KiB per line by default.
- Malformed records and collection limits are reported as data gaps.
- Rotated log archives are not collected automatically.
- Line references apply to the source file used for that investigation.
- Prometheus collection supports windows of at most one hour; wider windows skip metrics.
- Three fixed queries run sequentially with a five-second step and fifteen-second lookback.
- Each response allows one aggregated series, at most 721 points, and at most 256 KiB.
- Each metric query requests a two-second server timeout.
- HTTP timeouts are three seconds per phase and one second for connection establishment;
  these are not a total investigation deadline. Redirects and automatic retries are disabled.
- Only metric summaries and query references enter the report; raw time series are not persisted.
- Short incidents between evaluation points may be missed. Metric references depend on retention.
- The HTTP 504 counter is cumulative; per-window error counts and per-instance analysis are absent.
- Actuator collects current info and health only; it cannot reconstruct historical health.
- Actuator verifies declared service/environment identity before collecting health.
- Each Actuator response is limited to 64 KiB; additional payload fields are ignored.
- Valid HTTP 503 health statuses are retained; other invalid or failed responses become data gaps.
- Actuator URLs are live references, and raw snapshots are not persisted for later replay.
- Distributed traces are not connected.
- LLM input JSON is limited to 32,000 UTF-8 bytes, excluding instructions and schema.
- Model output is capped at 2,500 tokens.
- The SDK uses a 20-second timeout with automatic retries disabled; one investigation
  makes at most one model attempt. Retrying the HTTP investigation request is a new attempt.
- Requests use store=False; this does not imply zero provider data retention.
- PostgreSQL snapshots are optional; the default Compose demo does not enable storage.
- Saved history requires PostgreSQL; without it the workspace keeps one report in memory.
- Usage totals cover saved application calls, not every charge on the provider account.
  A failure to save a report can leave a billable call outside the dashboard.
- Costs use versioned standard-tier text prices for the supported model. Unknown usage,
  models, or service tiers remain unknown; estimates are not provider invoices.
- The local demo has no authentication, authorization, or automatic data-retention policy.
- Background workers and automatic incident detection are not implemented.
- No automatic patch generation, pull requests, deployment, or on-call notifications.
