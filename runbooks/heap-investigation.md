# Investigate JVM heap observations

## When to use

Use this runbook when an investigation contains JVM heap observations
or a hypothesis about memory pressure.

Scope: order-service in the local demo environment.

## What to inspect

1. Confirm the metric, unit, target, and incident window.
2. Inspect the available minimum, maximum, last value, and sample count.
3. Check for collection gaps.
4. Obtain a historical baseline under comparable workload.
5. Obtain heap limits, garbage-collection observations, and request load.
6. Look for explicit out-of-memory errors and lifecycle records.

## Evidence boundaries

A minimum, maximum, and last value do not describe the full time series.

A heap range without a baseline does not establish normal behavior,
stable memory pressure, a memory leak, or an out-of-memory condition.

A low last value does not prove that garbage collection resolved
an incident.

A counter drop or heap change alone does not establish a restart.

Temporal overlap does not establish that memory caused an order failure.

## Suggested next checks

Compare incident-era heap observations with comparable historical load.

Inspect retained garbage-collection logs and explicit memory errors
when those sources are available.

Request a more complete time series if summary values are insufficient.

## Operational limits

Do not automatically restart the process or change JVM memory settings.

Heap dumps require a separate operational decision because they can
consume resources and contain sensitive application data.

## Expected investigation output

Report the observed values and coverage. Separate measurements from
hypotheses and identify the missing baseline or diagnostic sources.