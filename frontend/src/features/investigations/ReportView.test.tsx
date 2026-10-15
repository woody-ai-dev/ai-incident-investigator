import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { reportSchema, type InvestigationRequest } from "../../api/contracts";
import { ReportView } from "./ReportView";

const request: InvestigationRequest = {
  service: "order-service",
  environment: "local",
  start_time: "2026-10-14T13:00:00+03:00",
  end_time: "2026-10-14T13:15:00+03:00",
  description: "Checkout requests time out.",
};
const report = reportSchema.parse({
  analysis_status: "completed",
  summary: "Payment timeout investigation.",
  evidence: [
    {
      id: "metric-errors",
      source: "metric",
      service: "order-service",
      summary: "HTTP 504 counter increased.",
      reference: "prometheus:http_504",
      start_time: "2026-10-14T10:02:00Z",
      end_time: "2026-10-14T10:15:00Z",
    },
    {
      id: "actuator-health",
      source: "actuator",
      service: "order-service",
      summary: "Application health is UP now.",
      reference: "actuator:health",
      start_time: "2026-10-14T10:20:00Z",
    },
    {
      id: "log-timeout",
      source: "log",
      service: "order-service",
      summary: "Payment request timed out.",
      reference: "local-jsonl:line:9",
      start_time: "2026-10-14T10:01:00Z",
    },
    {
      id: "trace-payment",
      source: "trace",
      service: "order-service",
      summary: "Payment span started.",
      reference: "trace:payment",
      start_time: "2026-10-14T10:00:00Z",
    },
  ],
  findings: [{ statement: "Checkout recorded a payment timeout.", evidence_ids: ["log-timeout"] }],
  hypotheses: [
    {
      statement: "A payment dependency may be slow.",
      supporting_evidence_ids: ["metric-errors"],
      contradicting_evidence_ids: ["actuator-health"],
    },
  ],
  recommended_checks: [
    {
      action: "Inspect payment latency.",
      reason: "Separate dependency delay from checkout delay.",
    },
  ],
  missing_data: ["No payment dependency logs were collected."],
});
const scrollMock = vi.fn();
const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");

beforeEach(() => {
  scrollMock.mockReset();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false })),
  );
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scrollMock,
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  if (originalScroll)
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScroll);
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
});

function blobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

function panelBounds(panel: HTMLElement, top: number, bottom: number) {
  vi.spyOn(panel, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: top,
    top,
    bottom,
    left: 0,
    right: 300,
    width: 300,
    height: bottom - top,
    toJSON: () => ({}),
  });
}

describe("investigation report", () => {
  it("exports the report with its original request and versioned context", async () => {
    const createUrl = vi.fn<(blob: Blob) => string>(() => "blob:report-test");
    const revokeUrl = vi.fn();
    vi.stubGlobal(
      "URL",
      Object.assign(class extends URL {}, {
        createObjectURL: createUrl,
        revokeObjectURL: revokeUrl,
      }),
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const timeout = vi.spyOn(window, "setTimeout");
    const user = userEvent.setup();
    render(<ReportView request={request} report={report} />);
    await user.click(screen.getByRole("button", { name: "Export JSON" }));
    expect(createUrl).toHaveBeenCalledOnce();
    const blob = createUrl.mock.calls[0]?.[0] as Blob | undefined;
    if (!blob) throw new Error("Export must create a JSON blob.");
    expect(blob.type).toBe("application/json");
    expect(JSON.parse(await blobText(blob))).toEqual({ schema_version: 1, request, report });
    expect(click).toHaveBeenCalledOnce();
    const link = click.mock.instances[0] as HTMLAnchorElement | undefined;
    expect(link).toHaveAttribute("href", "blob:report-test");
    expect(link).toHaveAttribute("download", "investigation-report.json");
    expect(link?.isConnected).toBe(false);
    expect(revokeUrl).not.toHaveBeenCalled();
    const cleanupIndex = timeout.mock.calls.findIndex((call) => call[1] === 1000);
    const cleanup = timeout.mock.calls[cleanupIndex]?.[0];
    const timer = timeout.mock.results[cleanupIndex]?.value as number;
    window.clearTimeout(timer);
    if (typeof cleanup !== "function") throw new Error("The export URL needs a cleanup timer.");
    cleanup();
    expect(revokeUrl).toHaveBeenCalledWith("blob:report-test");
  });

  it("displays UTC and separates sorted historical evidence from current Actuator snapshots", () => {
    render(<ReportView request={request} report={report} />);
    expect(screen.getByText(/14 Oct 2026, 10:00:00 → 14 Oct 2026, 10:15:00 UTC/)).toBeVisible();
    const historical = screen.getByRole("heading", {
      name: "Historical observations",
    }).nextElementSibling;
    if (!(historical instanceof HTMLElement))
      throw new Error("Historical observations must have a list.");
    const observations = within(historical).getAllByRole("button");
    expect(observations.map((button) => button.textContent)).toEqual([
      expect.stringContaining("trace-payment"),
      expect.stringContaining("log-timeout"),
      expect.stringContaining("metric-errors"),
    ]);
    expect(within(historical).queryByText("Application health is UP now.")).not.toBeInTheDocument();
    expect(
      screen.getByText("Actuator describes its observation time, not the incident window."),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: /Application health is UP now/ })).toHaveTextContent(
      "10:20:00 UTC",
    );
  });

  it("preserves source fractional seconds while converting offset timestamps to UTC", async () => {
    const preciseRequest = { ...request, start_time: "2026-10-14T13:00:01.123456+03:00" };
    const preciseReport = {
      ...report,
      evidence: report.evidence.map((item) =>
        item.id === "actuator-health"
          ? { ...item, start_time: "2026-10-14T13:20:02.001200+03:00" }
          : item,
      ),
    };
    const user = userEvent.setup();
    render(<ReportView request={preciseRequest} report={preciseReport} />);
    expect(
      screen.getByText(/14 Oct 2026, 10:00:01\.123456 → 14 Oct 2026, 10:15:00 UTC/),
    ).toBeVisible();
    const observation = screen.getByRole("button", { name: /Application health is UP now/ });
    expect(observation).toHaveTextContent("14 Oct 2026, 10:20:02.001200 UTC");
    await user.click(observation);
    expect(
      within(screen.getByRole("complementary", { name: "Evidence details" })).getByText(
        "14 Oct 2026, 10:20:02.001200 UTC",
      ),
    ).toBeVisible();
  });

  it("connects analysis references to accessible evidence details and restores focus on close", async () => {
    const user = userEvent.setup();
    render(<ReportView request={request} report={report} />);
    await user.click(screen.getByRole("button", { name: "Analysis & checks" }));
    expect(screen.getByText("Checkout recorded a payment timeout.")).toBeVisible();
    const hypothesis = screen.getByText("A payment dependency may be slow.").closest("article");
    if (!hypothesis) throw new Error("A hypothesis must show its references.");
    expect(within(hypothesis).getByText("Supports:")).toBeVisible();
    expect(within(hypothesis).getByText("Contradicts:")).toBeVisible();
    expect(screen.getByText("Inspect payment latency.")).toBeVisible();
    expect(screen.getByText("Separate dependency delay from checkout delay.")).toBeVisible();
    expect(screen.getByText(/Model conclusions require engineering review/)).toBeVisible();
    const reference = within(hypothesis).getByRole("button", { name: "metric-errors" });
    const panel = screen.getByRole("complementary", { name: "Evidence details" });
    panelBounds(panel, 100, 500);
    expect(reference).toHaveAttribute("aria-controls", panel.id);
    expect(reference).toHaveAttribute("aria-pressed", "false");
    reference.focus();
    await user.keyboard("{Enter}");
    expect(reference).toHaveAttribute("aria-pressed", "true");
    expect(panel).toHaveAttribute("tabindex", "-1");
    expect(panel).toHaveFocus();
    expect(within(panel).getByRole("heading", { name: "metric-errors" })).toBeVisible();
    expect(within(panel).getByText("prometheus:http_504")).toBeVisible();
    expect(within(panel).getByText("End")).toBeVisible();
    expect(scrollMock).not.toHaveBeenCalled();
    await user.tab();
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(reference).toHaveFocus();
    expect(reference).toHaveAttribute("aria-pressed", "false");
    expect(within(panel).getByRole("heading", { name: "Follow the evidence" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
  });

  it("scrolls to offscreen details only after an explicit evidence selection", async () => {
    const user = userEvent.setup();
    render(<ReportView request={request} report={report} />);
    const panel = screen.getByRole("complementary", { name: "Evidence details" });
    panelBounds(panel, 800, 1200);
    expect(scrollMock).not.toHaveBeenCalled();
    const evidence = screen.getByRole("button", { name: /Payment request timed out/ });
    await user.click(evidence);
    expect(evidence).toHaveAttribute("aria-controls", panel.id);
    expect(evidence).toHaveAttribute("aria-pressed", "true");
    expect(panel).toHaveFocus();
    expect(scrollMock).toHaveBeenCalledOnce();
    expect(scrollMock).toHaveBeenCalledWith({ behavior: "smooth", block: "nearest" });
  });

  it("honours reduced motion and does not return focus to a removed reference", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: true })),
    );
    const user = userEvent.setup();
    render(<ReportView request={request} report={report} />);
    const panel = screen.getByRole("complementary", { name: "Evidence details" });
    panelBounds(panel, 800, 1200);
    const evidence = screen.getByRole("button", { name: /Payment request timed out/ });
    await user.click(evidence);
    expect(scrollMock).toHaveBeenCalledWith({ behavior: "auto", block: "nearest" });
    await user.click(screen.getByRole("button", { name: "Analysis & checks" }));
    expect(evidence.isConnected).toBe(false);
    const focus = vi.spyOn(evidence, "focus");
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(focus).not.toHaveBeenCalled();
    expect(within(panel).getByRole("heading", { name: "Follow the evidence" })).toBeVisible();
  });

  it("clears a reused evidence ID on report replacement without changing the selected report tab", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<ReportView request={request} report={report} />);
    await user.click(screen.getByRole("button", { name: "Analysis & checks" }));
    await user.click(screen.getByRole("button", { name: "log-timeout" }));
    const panel = screen.getByRole("complementary", { name: "Evidence details" });
    expect(within(panel).getByRole("heading", { name: "log-timeout" })).toBeVisible();
    scrollMock.mockClear();
    const updated = {
      ...report,
      summary: "A new investigation report.",
      evidence: report.evidence.map((item) => ({ ...item, reference: `new:${item.reference}` })),
    };
    rerender(<ReportView request={{ ...request, description: "New window" }} report={updated} />);
    expect(screen.getByRole("button", { name: "Analysis & checks" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "log-timeout" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(within(panel).getByRole("heading", { name: "Follow the evidence" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
    expect(scrollMock).not.toHaveBeenCalled();
  });

  it.each([
    ["not_requested", "AI analysis disabled"],
    ["skipped", "AI analysis skipped"],
    ["failed", "AI analysis failed"],
  ] as const)("explains empty results with analysis status %s", async (analysis_status, label) => {
    const empty = reportSchema.parse({
      analysis_status,
      summary: "No observations were available.",
      evidence: [],
      findings: [],
      hypotheses: [],
      recommended_checks: [],
      missing_data: ["The requested time window did not contain matching logs."],
    });
    const user = userEvent.setup();
    render(<ReportView request={request} report={empty} />);
    expect(screen.getByText(label)).toBeVisible();
    expect(screen.getAllByText("No observations returned.")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Analysis & checks" }));
    expect(screen.getByText(`No findings returned. ${label}.`)).toBeVisible();
    expect(screen.getByText("No hypotheses returned.")).toBeVisible();
    expect(screen.getByText("No recommended checks returned.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Data gaps (1)" }));
    expect(
      screen.getByText("The requested time window did not contain matching logs."),
    ).toBeVisible();
  });

  it("renders untrusted report text and source references as text", async () => {
    const raw = '<img src=x onerror="alert(1)">';
    const unsafe = {
      ...report,
      summary: raw,
      evidence: [{ ...report.evidence[0]!, summary: "Raw source observation", reference: raw }],
      findings: [],
      hypotheses: [],
      missing_data: [],
    };
    const user = userEvent.setup();
    const { container } = render(<ReportView request={request} report={unsafe} />);
    expect(screen.getByText(raw)).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
    await user.click(screen.getByRole("button", { name: /Raw source observation/ }));
    const panel = screen.getByRole("complementary", { name: "Evidence details" });
    expect(within(panel).getByText(raw)).toBeVisible();
    expect(panel.querySelector("img")).toBeNull();
  });

  it("reports when a completed analysis has no data gaps", async () => {
    const user = userEvent.setup();
    render(<ReportView request={request} report={{ ...report, missing_data: [] }} />);
    await user.click(screen.getByRole("button", { name: "Data gaps (0)" }));
    expect(screen.getByText("No data gaps reported.")).toBeVisible();
  });
});
