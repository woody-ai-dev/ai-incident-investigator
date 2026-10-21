import { z } from "zod";

function text(minimum: number, maximum: number) {
  return z
    .string()
    .trim()
    .refine((value) => {
      // Python counts Unicode code points; JavaScript string.length counts UTF-16 units.
      const length = [...value].length;
      return length >= minimum && length <= maximum;
    }, `Use ${minimum}–${maximum} characters.`);
}

export const identifier = text(1, 100);
export const reportText = text(1, 4000);
export const timestamp = z.iso
  .datetime({ offset: true })
  .refine(
    (value) => Number(value.slice(0, 4)) >= 1 && Number.isFinite(Date.parse(value)),
    "Use a valid date and time with a timezone.",
  );

function instant(value: string): bigint {
  // Preserve Python's microsecond precision when comparing adjacent timestamps.
  const fraction = value.match(/\.(\d+)(?:Z|[+-])/i)?.[1] ?? "";
  const microseconds = fraction.padEnd(6, "0").slice(3, 6);
  return BigInt(Date.parse(value)) * 1000n + BigInt(microseconds);
}

export const requestSchema = z
  .strictObject({
    service: identifier,
    environment: identifier,
    start_time: timestamp,
    end_time: timestamp,
    description: text(0, 4000).nullable().optional(),
  })
  .superRefine((request, context) => {
    if (
      timestamp.safeParse(request.start_time).success &&
      timestamp.safeParse(request.end_time).success &&
      instant(request.end_time) <= instant(request.start_time)
    ) {
      context.addIssue({
        code: "custom",
        path: ["end_time"],
        message: "End time must be after start time.",
      });
    }
  });

const evidenceSourceSchema = z.enum(["log", "metric", "trace", "actuator"]);
const evidenceSchema = z
  .strictObject({
    id: identifier,
    source: evidenceSourceSchema,
    service: identifier,
    summary: reportText,
    reference: reportText,
    start_time: timestamp,
    end_time: timestamp.nullable().default(null),
  })
  .superRefine((evidence, context) => {
    if (
      evidence.end_time !== null &&
      timestamp.safeParse(evidence.start_time).success &&
      timestamp.safeParse(evidence.end_time).success &&
      instant(evidence.end_time) <= instant(evidence.start_time)
    ) {
      context.addIssue({
        code: "custom",
        path: ["end_time"],
        message: "Evidence end time must be after start time.",
      });
    }
  });

const collectionStatusSchema = z.enum([
  "collected",
  "partial",
  "empty",
  "disabled",
  "skipped",
  "error",
  "not_recorded",
]);

const sourceCollectionSchema = z
  .strictObject({
    source: evidenceSourceSchema,
    status: collectionStatusSchema,
    evidence_count: z.number().int().nonnegative(),
    duration_ms: z.number().int().nonnegative().nullable(),
    issues: z.array(reportText),
  })
  .superRefine((collection, context) => {
    if (
      ["empty", "disabled", "skipped", "error"].includes(collection.status) &&
      collection.evidence_count !== 0
    ) {
      context.addIssue({
        code: "custom",
        message: "This collection status cannot contain evidence.",
      });
    }
    if (collection.status === "collected" && collection.evidence_count === 0) {
      context.addIssue({ code: "custom", message: "Collected status requires evidence." });
    }
    if (collection.status === "disabled" && collection.duration_ms !== null) {
      context.addIssue({
        code: "custom",
        message: "Disabled collection must not have a duration.",
      });
    }
    if (
      !["disabled", "not_recorded"].includes(collection.status) &&
      collection.duration_ms === null
    ) {
      context.addIssue({ code: "custom", message: "Executed collection requires a duration." });
    }
    if (
      ["partial", "disabled", "skipped", "error"].includes(collection.status) &&
      collection.issues.length === 0
    ) {
      context.addIssue({ code: "custom", message: "Incomplete collection needs an explanation." });
    }
  });

export const reportSchema = z
  .strictObject({
    analysis_status: z
      .enum(["not_requested", "skipped", "completed", "failed"])
      .default("not_requested"),
    source_collections: z.array(sourceCollectionSchema).min(1).max(4).optional(),
    summary: reportText,
    evidence: z.array(evidenceSchema),
    findings: z.array(
      z.strictObject({
        statement: reportText,
        evidence_ids: z.array(identifier).min(1),
      }),
    ),
    hypotheses: z.array(
      z.strictObject({
        statement: reportText,
        supporting_evidence_ids: z.array(identifier).min(1),
        contradicting_evidence_ids: z.array(identifier).default(() => []),
      }),
    ),
    recommended_checks: z.array(z.strictObject({ action: reportText, reason: reportText })),
    missing_data: z.array(reportText),
  })
  .superRefine((report, context) => {
    const ids = new Set(report.evidence.map((item) => item.id));
    if (ids.size !== report.evidence.length) {
      context.addIssue({
        code: "custom",
        path: ["evidence"],
        message: "Evidence IDs must be unique.",
      });
    }
    const referenced = [
      ...report.findings.flatMap((item) => item.evidence_ids),
      ...report.hypotheses.flatMap((item) => [
        ...item.supporting_evidence_ids,
        ...item.contradicting_evidence_ids,
      ]),
    ];
    if (referenced.some((id) => !ids.has(id))) {
      context.addIssue({ code: "custom", message: "Report references unknown evidence." });
    }
    if (report.source_collections) {
      const sources = report.source_collections.map((item) => item.source);
      if (new Set(sources).size !== sources.length) {
        context.addIssue({
          code: "custom",
          path: ["source_collections"],
          message: "Collection sources must be unique.",
        });
      }
      for (const collection of report.source_collections) {
        const count = report.evidence.filter((item) => item.source === collection.source).length;
        if (collection.evidence_count !== count) {
          context.addIssue({
            code: "custom",
            path: ["source_collections"],
            message: "Collection count does not match report evidence.",
          });
        }
      }
    }
    if (report.evidence.length === 0 && report.missing_data.length === 0) {
      context.addIssue({
        code: "custom",
        path: ["missing_data"],
        message: "Missing evidence needs an explanation.",
      });
    }
  });

export type InvestigationRequest = z.infer<typeof requestSchema>;
export type InvestigationReport = z.infer<typeof reportSchema>;
export type Evidence = z.infer<typeof evidenceSchema>;
export type EvidenceSource = z.infer<typeof evidenceSourceSchema>;

export type CollectionStatus = z.infer<typeof collectionStatusSchema>;
export type SourceCollection = z.infer<typeof sourceCollectionSchema>;
