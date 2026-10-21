import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, createInvestigation } from "./client";
import {
  reportSchema,
  requestSchema,
  type Evidence,
  type InvestigationReport,
  type InvestigationRequest,
} from "./contracts";

const request: InvestigationRequest = {
  service: "order-service",
  environment: "local",
  start_time: "2026-10-14T10:00:00Z",
  end_time: "2026-10-14T10:10:00Z",
};
const evidence: Evidence = {
  id: "log-1",
  source: "log",
  service: "order-service",
  summary: "[ERROR] Payment timed out.",
  reference: "local-jsonl:line:1",
  start_time: "2026-10-14T10:01:00Z",
  end_time: null,
};

function report(
  status: InvestigationReport["analysis_status"] = "not_requested",
): InvestigationReport {
  return {
    analysis_status: status,
    summary: "Collected service evidence.",
    evidence: [{ ...evidence }],
    findings: [],
    hypotheses: [],
    recommended_checks: [],
    missing_data: ["Traces unavailable."],
  };
}

const fetchMock = vi.fn<typeof fetch>();
const signal = new AbortController().signal;
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("investigation API contract", () => {
  it("sends a normalized JSON request and forwards its abort signal", async () => {
    fetchMock.mockResolvedValue(Response.json(report()));
    const result = await createInvestigation(
      { ...request, service: " order-service ", description: "  Timeout  " },
      signal,
    );
    expect(result.report.evidence).toEqual([evidence]);
    expect(fetchMock).toHaveBeenCalledWith("/api/investigations", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ ...request, description: "Timeout" }),
      signal,
    });
  });

  it("matches Python character limits and compares aware timestamps at microsecond precision", () => {
    expect(requestSchema.safeParse({ ...request, service: "🔥".repeat(100) }).success).toBe(true);
    expect(requestSchema.safeParse({ ...request, service: "🔥".repeat(101) }).success).toBe(false);
    expect(requestSchema.safeParse({ ...request, description: "🔥".repeat(4000) }).success).toBe(
      true,
    );
    expect(requestSchema.safeParse({ ...request, start_time: "2026-10-14T10:00:00" }).success).toBe(
      false,
    );
    expect(
      requestSchema.safeParse({ ...request, start_time: "0000-10-14T10:00:00Z" }).success,
    ).toBe(false);
    expect(requestSchema.safeParse({ ...request, end_time: request.start_time }).success).toBe(
      false,
    );
    expect(
      requestSchema.safeParse({
        ...request,
        start_time: "2026-10-14T10:00:00.123456Z",
        end_time: "2026-10-14T10:00:00.123457Z",
      }).success,
    ).toBe(true);
  });

  it("rejects duplicate evidence IDs and broken finding or hypothesis references", () => {
    expect(reportSchema.safeParse({ ...report(), evidence: [evidence, evidence] }).success).toBe(
      false,
    );
    expect(
      reportSchema.safeParse({
        ...report(),
        findings: [{ statement: "Payment failed.", evidence_ids: ["missing"] }],
      }).success,
    ).toBe(false);
    expect(
      reportSchema.safeParse({
        ...report(),
        hypotheses: [
          {
            statement: "Payment issue.",
            supporting_evidence_ids: ["log-1"],
            contradicting_evidence_ids: ["missing"],
          },
        ],
      }).success,
    ).toBe(false);
  });

  it("validates evidence ranges and allows live Actuator timestamps outside an incident window", () => {
    expect(
      reportSchema.safeParse({
        ...report(),
        evidence: [{ ...evidence, end_time: evidence.start_time }],
      }).success,
    ).toBe(false);
    expect(
      reportSchema.safeParse({
        ...report(),
        evidence: [{ ...evidence, source: "actuator", start_time: "2026-10-15T12:00:00+03:00" }],
      }).success,
    ).toBe(true);
  });

  it("rejects a malformed HTTP 200 report without echoing its body", async () => {
    fetchMock.mockResolvedValue(Response.json({ summary: "private-body" }));
    const error: unknown = await createInvestigation(request, signal).catch(
      (cause: unknown) => cause,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 200 });
    expect(String(error)).not.toContain("private-body");
  });

  it("maps only known validation fields and never exposes server inputs or messages", async () => {
    fetchMock.mockResolvedValue(
      Response.json(
        {
          detail: [
            {
              loc: ["body", "service"],
              type: "string_too_long",
              msg: "private-message",
              input: "private-input",
            },
            { loc: ["body", "__proto__"], type: "value_error", msg: "private-message" },
            { loc: ["body"], type: "value_error", input: "private-input" },
          ],
        },
        { status: 422 },
      ),
    );
    const error: unknown = await createInvestigation(request, signal).catch(
      (cause: unknown) => cause,
    );
    expect(error).toMatchObject({
      status: 422,
      fieldErrors: { service: "Use a service name with 1–100 characters." },
    });
    expect(JSON.stringify(error)).not.toContain("private-");
    expect(String(error)).not.toContain("private-");
  });

  it("handles non-JSON server failures with a safe status message", async () => {
    fetchMock.mockResolvedValue(new Response("<html>private-stack</html>", { status: 500 }));
    await expect(createInvestigation(request, signal)).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      message: "The investigation API returned HTTP 500.",
    });
  });

  it("replaces transport errors with a safe API error", async () => {
    fetchMock.mockRejectedValue(new TypeError("private-network-details"));
    await expect(createInvestigation(request, signal)).rejects.toMatchObject({
      name: "ApiError",
      status: null,
      message: "Could not connect to the investigator API.",
    });
  });

  it("preserves AbortError so a cancelled request is not shown as a server failure", async () => {
    const aborted = new DOMException("Cancelled", "AbortError");
    fetchMock.mockRejectedValue(aborted);
    await expect(createInvestigation(request, signal)).rejects.toBe(aborted);
  });

  it("preserves evidence when HTTP 200 reports that LLM analysis failed", async () => {
    fetchMock.mockResolvedValue(Response.json(report("failed")));
    const result = await createInvestigation(request, signal);
    expect(result.report.analysis_status).toBe("failed");
    expect(result.report.evidence).toEqual([evidence]);
  });

  it("rejects invalid input before issuing an HTTP request", async () => {
    await expect(createInvestigation({ ...request, service: "  " }, signal)).rejects.toMatchObject({
      name: "ApiError",
      status: null,
      fieldErrors: { service: expect.any(String) },
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires a data gap when evidence is empty and rejects unknown fields", () => {
    expect(reportSchema.safeParse({ ...report(), evidence: [], missing_data: [] }).success).toBe(
      false,
    );
    expect(reportSchema.safeParse({ ...report(), unexpected: true }).success).toBe(false);
    expect(requestSchema.safeParse({ ...request, unexpected: true }).success).toBe(false);
  });
});

it("captures a committed snapshot UUID without losing a report when the header is absent or malformed", async () => {
  for (const rawId of [null, "not-a-uuid", "d9048d0d-669e-45b6-a199-a37db5d55a95"]) {
    fetchMock.mockResolvedValue(
      Response.json(report(), { headers: rawId ? { "X-Investigation-ID": rawId } : {} }),
    );
    const result = await createInvestigation(request, signal);
    expect(result.report).toEqual(report());
    expect(result.id).toBe(rawId?.startsWith("d904") ? rawId : null);
  }
});
