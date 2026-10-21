import type { InvestigationReport, InvestigationRequest } from "../src/api/contracts";

export const investigationRequest: InvestigationRequest = {
  service: "order-service",
  environment: "local",
  start_time: "2026-10-02T19:00:00.000Z",
  end_time: "2026-10-02T19:15:00.000Z",
  description: "Orders fail with PAYMENT_TIMEOUT.",
};

// A completed response fixture exercises analysis navigation without an LLM call.
export const investigationReport: InvestigationReport = {
  analysis_status: "completed",
  summary: "Collected telemetry includes a payment timeout and a cumulative HTTP 504 counter.",
  evidence: [
    {
      id: "log-timeout",
      source: "log",
      service: "order-service",
      summary: "Payment request timed out.",
      reference: "local-jsonl:line:42",
      start_time: "2026-10-02T19:01:05.123456Z",
      end_time: null,
    },
    {
      id: "metric-errors",
      source: "metric",
      service: "order-service",
      summary: "The cumulative HTTP 504 counter reached 3.",
      reference:
        "http://prometheus:9090/api/v1/query_range?query=http_server_requests_seconds_count",
      start_time: "2026-10-02T19:00:00Z",
      end_time: "2026-10-02T19:15:00Z",
    },
    {
      id: "actuator-health",
      source: "actuator",
      service: "order-service",
      summary: "Current application health is UP.",
      reference: "fixture:actuator/health",
      start_time: "2026-10-02T20:00:00Z",
      end_time: null,
    },
  ],
  findings: [
    {
      statement: "A payment timeout was recorded.",
      evidence_ids: ["log-timeout"],
    },
  ],
  hypotheses: [
    {
      statement: "A payment dependency may be slow.",
      supporting_evidence_ids: ["log-timeout", "metric-errors"],
      contradicting_evidence_ids: [],
    },
  ],
  recommended_checks: [
    {
      action: "Inspect payment latency.",
      reason: "Separate dependency delay from order delay.",
    },
  ],
  missing_data: [
    "Distributed traces were not available.",
    "Actuator is a current snapshot outside the incident window.",
  ],
};

export const savedId = "d9048d0d-669e-45b6-a199-a37db5d55a95";
export const savedInvestigation = {
  id: savedId,
  created_at: "2026-10-20T12:00:00.123456Z",
  schema_version: 1,
  duration_ms: 1234,
  configured_model: "fixture-model",
  prompt_sha256: "a".repeat(64),
  request: investigationRequest,
  report: investigationReport,
} as const;
export const historyItem = {
  id: savedId,
  created_at: savedInvestigation.created_at,
  service: investigationRequest.service,
  environment: investigationRequest.environment,
  duration_ms: 1234,
  configured_model: "fixture-model",
  analysis_status: investigationReport.analysis_status,
  summary: investigationReport.summary,
};
