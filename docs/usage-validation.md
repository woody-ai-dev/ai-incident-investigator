# Model usage validation

Validated on 2026-10-21 with one billable Responses API request to
`gpt-4.1-mini-2025-04-14`, standard service tier. SDK retries were disabled.
The input contained only the recorded synthetic payment-timeout fixture.

| Provider-reported value | Result |
| --- | ---: |
| Input tokens | 2,127 |
| Cached input tokens | 0 |
| Output tokens | 261 |
| Total tokens | 2,388 |
| Estimated cost, USD | 0.0012684 |
| Adapter duration | 11,863 ms |
| Analysis status | completed |

An HTTP response hook captured the provider usage before the application parsed the
answer. Counts matched the returned investigation, its PostgreSQL snapshot, daily
aggregates, period totals, and largest-analysis rankings. Reading the saved report
and all three rankings made no further model requests.

Chromium also rendered the captured real response on the Usage page and saved-report
page: 2,388 tokens and `$0.001268` after display rounding. This UI check replayed the
captured API data and made no additional provider requests.

Cost was independently recalculated with `Decimal` using the
[published standard text rates](https://developers.openai.com/api/docs/models/gpt-4.1-mini):

```text
((2127 - 0) × $0.40 + 0 × $0.10 + 261 × $1.60) / 1,000,000
= $0.0012684
```

This verifies accounting for one successful request. Provider invoice reconciliation
was not performed, and this call had no cached tokens. Offline tests cover cached
input, unknown pricing, missing usage, invalid answers, failed requests, and rejected
analysis. API credentials and HTTP authorization headers are excluded from artifacts.
