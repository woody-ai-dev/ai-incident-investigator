import { z } from "zod";
import { ApiError, readJson, fetchApi } from "./client";
import { reportSchema, requestSchema, timestamp, identifier, reportText } from "./contracts";

const analysisStatus = z.enum(["not_requested", "skipped", "completed", "failed"]);
export const storedInvestigationSchema = z.strictObject({
  id: z.uuid(),
  created_at: timestamp,
  schema_version: z.literal(1),
  duration_ms: z.number().int().nonnegative(),
  configured_model: z.string().nullable(),
  prompt_sha256: z
    .string()
    .regex(/^[a-f0-9]{64}$/)
    .nullable(),
  request: requestSchema,
  report: reportSchema,
});
const summarySchema = z.strictObject({
  id: z.uuid(),
  created_at: timestamp,
  service: identifier,
  environment: identifier,
  duration_ms: z.number().int().nonnegative(),
  configured_model: z.string().nullable(),
  analysis_status: analysisStatus,
  summary: reportText,
});
export const historyPageSchema = z.strictObject({
  items: z.array(summarySchema).max(100),
  next_cursor: z.string().min(1).max(512).nullable(),
});
export type StoredInvestigation = z.infer<typeof storedInvestigationSchema>;
export type HistoryPage = z.infer<typeof historyPageSchema>;

async function readHistory<T>(path: string, schema: z.ZodType<T>, signal: AbortSignal): Promise<T> {
  const response = await fetchApi(path, { headers: { Accept: "application/json" }, signal });
  if (!response.ok) {
    const message =
      response.status === 503
        ? "History is unavailable. Check that PostgreSQL storage is configured and running."
        : response.status === 404
          ? "This saved investigation was not found."
          : response.status === 422
            ? "The history filters or page link are invalid. Reset the filters and try again."
            : `Could not load saved investigations (HTTP ${response.status}).`;
    throw new ApiError(message, response.status);
  }
  const parsed = schema.safeParse(await readJson(response));
  if (!parsed.success)
    throw new ApiError("The API returned invalid saved investigation data.", response.status);
  return parsed.data;
}

export function listInvestigations(query: string, signal: AbortSignal): Promise<HistoryPage> {
  return readHistory(`/api/investigations${query ? `?${query}` : ""}`, historyPageSchema, signal);
}

export function getInvestigation(id: string, signal: AbortSignal): Promise<StoredInvestigation> {
  if (!z.uuid().safeParse(id).success) {
    return Promise.reject(new ApiError("This saved investigation link is invalid.", 422));
  }
  return readHistory(`/api/investigations/${id}`, storedInvestigationSchema, signal);
}
