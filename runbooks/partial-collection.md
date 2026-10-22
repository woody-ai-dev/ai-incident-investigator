# Investigate incomplete telemetry collection

## When to use

Use this runbook when a source outcome is partial, empty, disabled,
skipped, error, or not recorded, or when coverage gaps are reported.

Scope: order-service in the local demo environment.

## What to inspect

1. Review each source outcome and its reported issues.
2. Distinguish unavailable sources from successful empty results.
3. Confirm the requested service, environment, and time window.
4. Check source configuration and reachability using existing diagnostics.
5. Confirm that collected observations belong to the requested target.
6. Separate current Actuator snapshots from historical telemetry.
7. Preserve all usable evidence from successful sources.

## Evidence boundaries

A collector error is not proof that the application is unhealthy.

An empty result is not proof that the incident did not happen.

A successfully collected Actuator DOWN response is evidence of the
observed current state, not a collection failure.

Missing observations do not establish continuous uptime or downtime.

A later snapshot cannot fill a historical coverage gap.

## Suggested next checks

For an error, inspect the reported collection issue and source
configuration.

For an empty result, verify the target and time window before widening
the investigation.

For partial coverage, seek retained incident-era observations from
an additional source.

## Operational limits

Do not silently widen the incident window, substitute another environment,
or discard evidence from sources that succeeded.

Do not present a source configuration check as an executed action.

## Expected investigation output

State which observations are available, which sources are incomplete,
and how those gaps limit the conclusions.