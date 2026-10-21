import { afterEach, expect, it, vi } from "vitest";
import { reportSchema } from "./contracts";
import { llmUsageSchema } from "./llmUsage";
import { getUsage } from "./usage";

const usage = {
  provider: "openai",
  requested_model: "gpt-4.1-mini-2025-04-14",
  response_model: "gpt-4.1-mini-2025-04-14",
  service_tier: "default",
  started_at: "2026-10-21T12:00:00Z",
  duration_ms: 1000,
  tokens: { input_tokens: 1000, cached_input_tokens: 400, output_tokens: 100, total_tokens: 1100 },
  pricing: {
    catalog_version: "test",
    currency: "USD",
    input_per_million: "0.40",
    cached_input_per_million: "0.10",
    output_per_million: "1.60",
  },
  estimated_cost_usd: "0.00044",
};
afterEach(() => vi.unstubAllGlobals());

it("accepts provider accounting while preserving old reports without it", () => {
  const report = {
    summary: "Saved report",
    evidence: [],
    findings: [],
    hypotheses: [],
    recommended_checks: [],
    missing_data: ["No logs"],
  };
  expect(reportSchema.parse(report).llm_usage).toBeUndefined();
  expect(reportSchema.parse({ ...report, llm_usage: usage }).llm_usage?.tokens?.total_tokens).toBe(
    1100,
  );
});

it("rejects impossible token counts and unknown cost without a price", () => {
  expect(
    llmUsageSchema.safeParse({ ...usage, tokens: { ...usage.tokens, cached_input_tokens: 1001 } })
      .success,
  ).toBe(false);
  expect(
    llmUsageSchema.safeParse({ ...usage, tokens: { ...usage.tokens, total_tokens: 1101 } }).success,
  ).toBe(false);
  expect(llmUsageSchema.safeParse({ ...usage, pricing: null }).success).toBe(false);
});

it("handles storage failure and forwards cancellation", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response("{}", { status: 503 }));
  vi.stubGlobal("fetch", fetch);
  const signal = new AbortController().signal;
  await expect(getUsage(7, "tokens", signal)).rejects.toThrow("Usage is currently unavailable");
  expect(fetch).toHaveBeenCalledWith(
    "/api/usage?days=7&sort=tokens",
    expect.objectContaining({ signal }),
  );
});

it("rejects an invalid successful response", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 200 })));
  await expect(getUsage(7, "cost", new AbortController().signal)).rejects.toThrow(
    "invalid usage statistics",
  );
});
