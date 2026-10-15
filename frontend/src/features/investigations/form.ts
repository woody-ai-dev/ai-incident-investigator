import { requestSchema, type InvestigationRequest } from "../../api/contracts";
import { INVESTIGATION_TARGETS } from "./targets";

export type FormValues = Record<
  "service" | "environment" | "start_time" | "end_time" | "description",
  string
>;
type TimeWindow = Pick<InvestigationRequest, "start_time" | "end_time">;

function localTimestamp(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 19);
}

export function recentWindow(now: Date = new Date()): TimeWindow {
  return {
    start_time: new Date(now.getTime() - 15 * 60_000).toISOString(),
    end_time: now.toISOString(),
  };
}

export function defaultValues(now: Date = new Date()): FormValues {
  return {
    service: INVESTIGATION_TARGETS[0].service,
    environment: INVESTIGATION_TARGETS[0].environments[0],
    start_time: localTimestamp(new Date(now.getTime() - 15 * 60_000)),
    end_time: localTimestamp(now),
    description: "",
  };
}

function parseLocalTimestamp(value: string): string {
  const parts = value.match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/,
  );
  if (!parts) return "";
  const date = new Date(value);
  const components = [
    date.getFullYear(),
    date.getMonth() + 1,
    date.getDate(),
    date.getHours(),
    date.getMinutes(),
    date.getSeconds(),
    date.getMilliseconds(),
  ];
  const expected = [
    ...parts.slice(1, 6).map(Number),
    Number(parts[6] ?? "0"),
    Number((parts[7] ?? "").padEnd(3, "0")),
  ];
  // JavaScript normalizes impossible dates and DST gaps. Reject the changed wall time.
  if (components.some((component, index) => component !== expected[index])) return "";
  return date.toISOString();
}

export function validateForm(
  values: FormValues,
  timeWindow?: TimeWindow,
): {
  request?: InvestigationRequest;
  errors: Record<string, string>;
} {
  const result = requestSchema.safeParse({
    ...values,
    start_time: timeWindow?.start_time ?? parseLocalTimestamp(values.start_time),
    end_time: timeWindow?.end_time ?? parseLocalTimestamp(values.end_time),
    description: values.description.trim() || null,
  });
  if (result.success) return { request: result.data, errors: {} };
  const errors: Record<string, string> = {};
  for (const issue of result.error.issues) {
    const field = String(issue.path[0] ?? "form");
    errors[field] ??= issue.message;
  }
  return { errors };
}
