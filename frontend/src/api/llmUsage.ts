import { z } from "zod";

const count = z.number().int().nonnegative();
export const money = z
  .string()
  .max(40)
  .regex(/^\d+(?:\.\d+)?$/)
  .refine((value) => Number.isFinite(Number(value)));
const tokens = z
  .strictObject({
    input_tokens: count,
    cached_input_tokens: count,
    output_tokens: count,
    total_tokens: count,
  })
  .refine(
    (value) =>
      value.cached_input_tokens <= value.input_tokens &&
      value.total_tokens === value.input_tokens + value.output_tokens,
    "Invalid token counts.",
  );

export const llmUsageSchema = z
  .strictObject({
    provider: z.literal("openai"),
    requested_model: z.string().min(1).max(200),
    response_model: z.string().min(1).max(200).nullable(),
    service_tier: z.string().nullable(),
    started_at: z.iso.datetime({ offset: true }),
    duration_ms: count,
    tokens: tokens.nullable(),
    pricing: z
      .strictObject({
        catalog_version: z.string(),
        currency: z.literal("USD"),
        input_per_million: money,
        cached_input_per_million: money,
        output_per_million: money,
      })
      .nullable(),
    estimated_cost_usd: money.nullable(),
  })
  .refine(
    (value) =>
      value.estimated_cost_usd === null || (value.tokens !== null && value.pricing !== null),
    "Cost requires tokens and pricing.",
  );

export type LLMUsage = z.infer<typeof llmUsageSchema>;
