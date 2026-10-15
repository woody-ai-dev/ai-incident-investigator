import { z } from "zod";

import {
  reportSchema,
  requestSchema,
  type InvestigationReport,
  type InvestigationRequest,
} from "./contracts";

export class ApiError extends Error {
  readonly status: number | null;
  readonly fieldErrors: Record<string, string>;

  constructor(
    message: string,
    status: number | null = null,
    fieldErrors: Record<string, string> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

const fieldMessages = {
  service: "Use a service name with 1–100 characters.",
  environment: "Use an environment name with 1–100 characters.",
  start_time: "Use a valid start time with a timezone.",
  end_time: "Use a valid end time after the start time.",
  description: "Use no more than 4,000 characters.",
} as const;

function isRequestField(field: unknown): field is keyof typeof fieldMessages {
  return typeof field === "string" && Object.hasOwn(fieldMessages, field);
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" && error !== null && "name" in error && error.name === "AbortError"
  );
}

const validationErrorSchema = z.object({
  detail: z.array(
    z.object({
      loc: z.array(z.union([z.string(), z.number()])),
      type: z.string(),
    }),
  ),
});

function serverFieldErrors(payload: unknown): Record<string, string> {
  const result: Record<string, string> = {};
  const parsed = validationErrorSchema.safeParse(payload);
  if (!parsed.success) return result;
  for (const issue of parsed.data.detail.slice(0, 50)) {
    const field = issue.loc[0] === "body" ? issue.loc[1] : undefined;
    if (isRequestField(field)) {
      result[field] = fieldMessages[field];
    }
  }
  return result;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return (await response.json()) as unknown;
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError("The server returned an invalid response.", response.status);
  }
}

export async function createInvestigation(
  request: InvestigationRequest,
  signal: AbortSignal,
): Promise<InvestigationReport> {
  const parsed = requestSchema.safeParse(request);
  if (!parsed.success) {
    const fields: Record<string, string> = {};
    for (const issue of parsed.error.issues) {
      const field = issue.path[0];
      if (isRequestField(field)) {
        fields[field] = issue.message;
      }
    }
    throw new ApiError("Check the investigation details.", null, fields);
  }

  let response: Response;
  try {
    response = await fetch("/api/investigations", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(parsed.data),
      signal,
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError("Could not connect to the investigator API.");
  }

  if (response.status === 422) {
    let payload: unknown;
    try {
      payload = await readJson(response);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
    }
    throw new ApiError(
      "The API rejected the investigation details.",
      422,
      serverFieldErrors(payload),
    );
  }
  if (!response.ok) {
    throw new ApiError(`The investigation API returned HTTP ${response.status}.`, response.status);
  }

  const report = reportSchema.safeParse(await readJson(response));
  if (!report.success)
    throw new ApiError("The API returned an invalid investigation report.", response.status);
  return report.data;
}
