import type { CollectionStatus, SourceCollection } from "../../api/contracts";

const labels: Record<CollectionStatus, string> = {
  collected: "Collected",
  partial: "Partial",
  empty: "No matching data",
  disabled: "Disabled",
  skipped: "Skipped",
  error: "Collection failed",
  not_recorded: "Not recorded",
};

export function evidenceCount(count: number): string {
  return count === 0 ? "No evidence" : `${count} evidence item${count === 1 ? "" : "s"}`;
}

export function collectionEvidenceLabel(
  collection: SourceCollection | undefined,
  count: number,
): string {
  if (!collection || collection.status === "collected" || collection.status === "not_recorded") {
    return evidenceCount(count);
  }
  if (collection.status === "partial") return `Partial · ${count} item${count === 1 ? "" : "s"}`;
  return labels[collection.status];
}

export function collectionSummary(collection: SourceCollection | undefined): string {
  if (!collection) return "Not recorded";
  const status = labels[collection.status];
  return collection.duration_ms === null
    ? status
    : `${status} · ${collection.duration_ms.toLocaleString()} ms`;
}
