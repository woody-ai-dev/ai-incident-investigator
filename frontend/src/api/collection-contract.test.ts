import { expect, it } from "vitest";
import { reportSchema } from "./contracts";

const legacy = {
  analysis_status: "not_requested",
  summary: "Legacy report",
  evidence: [],
  findings: [],
  hypotheses: [],
  recommended_checks: [],
  missing_data: ["No matching logs"],
};
const collection = {
  source: "log",
  status: "empty",
  evidence_count: 0,
  duration_ms: 12,
  issues: [],
};

it("accepts old JSON without adding fabricated collection metadata", () => {
  const parsed = reportSchema.parse(legacy);
  expect(parsed.source_collections).toBeUndefined();
  expect(JSON.parse(JSON.stringify(parsed))).toEqual(legacy);
});

it("accepts explicit empty data without treating the source as disabled", () => {
  const parsed = reportSchema.parse({ ...legacy, source_collections: [collection] });
  expect(parsed.source_collections?.[0]).toEqual(collection);
});

it.each([
  { source_collections: [{ ...collection, status: "collected" }] },
  { source_collections: [{ ...collection, status: "disabled" }] },
  { source_collections: [{ ...collection, status: "error", issues: [] }] },
  { source_collections: [{ ...collection, duration_ms: null }] },
  {
    source_collections: [
      { ...collection, status: "partial", evidence_count: 1, issues: ["Truncated"] },
    ],
  },
  { source_collections: [collection, collection] },
])("rejects inconsistent collection metadata: %j", ({ source_collections }) => {
  expect(reportSchema.safeParse({ ...legacy, source_collections }).success).toBe(false);
});
