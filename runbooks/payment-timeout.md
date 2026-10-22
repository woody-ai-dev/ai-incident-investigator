# Investigate a payment timeout

## When to use

Use this runbook when order-service logs contain a payment timeout or
an investigation contains HTTP 504 counter observations.

Scope: the local demo environment.

## What to inspect

1. Confirm the service, environment, and requested incident window.
2. Inspect timeout log records inside that window.
3. Record any available order or request identifiers.
4. Distinguish explicitly simulated timeouts from unexplained failures.
5. Inspect available request-duration observations and timeout configuration.
6. Check whether deployment or lifecycle records overlap the incident window.
7. List unavailable sources before proposing a cause.

## Evidence boundaries

A cumulative HTTP 504 counter is not the number of failures inside
the requested window.

Successful Prometheus evaluation values do not prove successful orders
or uninterrupted availability.

A current Actuator health snapshot does not establish historical health.

A timeout alone does not identify the failing dependency or prove
that a payment was not processed.

The local demo simulates a payment gateway. Its timeout does not prove
that an external provider was contacted.

## Suggested next checks

For the local demo, inspect the configured failure mode and correlate
the timeout with the matching order log records.

If investigating a real integration, obtain dependency request records,
timeout settings, and retry behavior before recommending another payment
attempt.

## Operational limits

Do not automatically retry a payment, change a timeout, restart a service,
or claim that a suggested check has already been executed.

## Expected investigation output

Describe the observed timeout, cite its telemetry evidence, and state
which additional observations are needed to distinguish possible causes.