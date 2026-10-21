import type { InvestigationReport } from "../../api/contracts";

export const analysisLabels: Record<InvestigationReport["analysis_status"], string> = {
  not_requested: "LLM disabled",
  skipped: "Analysis skipped",
  completed: "Analysis completed",
  failed: "Analysis failed",
};

export function savedTime(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}

export function localInput(value: string | null): string {
  if (!value || !Number.isFinite(Date.parse(value))) return "";
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 19);
}
