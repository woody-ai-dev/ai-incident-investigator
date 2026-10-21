import { z } from "zod";
import { ApiError, fetchApi, readJson } from "./client";
import { identifier, timestamp } from "./contracts";
import { money } from "./llmUsage";

const count = z.number().int().nonnegative();
const totals = {
  calls: count,
  reported_calls: count,
  priced_calls: count,
  input_tokens: count,
  cached_input_tokens: count,
  output_tokens: count,
  total_tokens: count,
  estimated_cost_usd: money,
};
export const usageDashboardSchema = z.strictObject({
  generated_at: timestamp,
  start_time: timestamp,
  end_time: timestamp,
  totals: z.strictObject(totals),
  daily: z
    .array(z.strictObject({ day: z.iso.date(), ...totals }))
    .min(1)
    .max(30),
  largest: z
    .array(
      z.strictObject({
        investigation_id: z.uuid(),
        service: identifier,
        environment: identifier,
        started_at: timestamp,
        duration_ms: count,
        total_tokens: count.nullable(),
        estimated_cost_usd: money.nullable(),
      }),
    )
    .max(5),
});
export type UsageDashboardData = z.infer<typeof usageDashboardSchema>;
export type UsageSort = "tokens" | "cost" | "duration";

export async function getUsage(days: number, sort: UsageSort, signal: AbortSignal) {
  const query = new URLSearchParams({ days: String(days), sort });
  const response = await fetchApi(`/api/usage?${query}`, {
    signal,
    headers: { Accept: "application/json" },
  });
  if (response.status === 503)
    throw new ApiError("Usage is currently unavailable. Check the service and try again.", 503);
  if (!response.ok)
    throw new ApiError(`Could not load usage (HTTP ${response.status}).`, response.status);
  const result = usageDashboardSchema.safeParse(await readJson(response));
  if (!result.success) throw new ApiError("The API returned invalid usage statistics.");
  return result.data;
}
