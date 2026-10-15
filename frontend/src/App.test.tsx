import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { ApiError, createInvestigation } from "./api/client";
import { reportSchema, type InvestigationReport } from "./api/contracts";

vi.mock("./api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/client")>();
  return { ...actual, createInvestigation: vi.fn() };
});

const report = reportSchema.parse({
  summary: "Collected four observations without generating conclusions.",
  evidence: [
    ["log-1", "log"],
    ["log-2", "log"],
    ["metric-up", "metric"],
    ["actuator-health", "actuator"],
  ].map(([id, source]) => ({
    id,
    source,
    service: "order-service",
    summary: `${id} observation`,
    reference: "Recorded demo observation",
    start_time: "2026-10-14T10:00:00Z",
  })),
  findings: [],
  hypotheses: [],
  recommended_checks: [],
  missing_data: ["Traces unavailable."],
});
const createMock = vi.mocked(createInvestigation);
const scrollMock = vi.fn();
const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");

beforeEach(() => {
  createMock.mockReset();
  scrollMock.mockReset();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: true })),
  );
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scrollMock,
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  if (originalScroll)
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScroll);
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
});

describe("investigation workspace", () => {
  it("shows a fast response in the evidence flow, with real counts and a visible request status", async () => {
    createMock.mockResolvedValue(report);
    const user = userEvent.setup();
    render(<App />);
    const button = screen.getByRole("button", { name: "Investigate" });
    const form = button.closest("form");
    if (!form) throw new Error("Investigation controls must belong to a form.");
    await user.click(button);

    expect(await screen.findByRole("region", { name: "Investigation report" })).toBeVisible();
    expect(createMock).toHaveBeenCalledWith(
      expect.objectContaining({ service: "order-service", environment: "local" }),
      expect.any(AbortSignal),
    );
    const graph = screen.getByRole("img", { name: /Logs: 2 evidence items/ });
    expect(graph).toHaveAccessibleName(/Metrics: 1 evidence item/);
    expect(graph).toHaveAccessibleName(/Actuator: 1 evidence item/);
    expect(graph).toHaveAccessibleName(/Evidence: 4 evidence items/);
    expect(graph).toHaveAccessibleName(/LLM disabled/);
    expect(within(form).getByRole("status")).toHaveTextContent(/received|complete|4/i);
    expect(screen.getByRole("region", { name: "Evidence flow" })).not.toHaveFocus();
    expect(scrollMock).not.toHaveBeenCalled();
  });

  it("keeps the pending flow and status visible until the response arrives", async () => {
    let resolve!: (value: InvestigationReport) => void;
    const pending = new Promise<InvestigationReport>((complete) => {
      resolve = complete;
    });
    createMock.mockReturnValue(pending);
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: "Investigate" }));

    const stop = screen.getByRole("button", { name: "Stop waiting" });
    const form = stop.closest("form");
    if (!form) throw new Error("Investigation controls must belong to a form.");
    expect(screen.getByText("Awaiting response")).toBeVisible();
    expect(screen.getByRole("img", { name: /Logs: Awaiting report/ })).toBeVisible();
    expect(within(form).getByRole("status")).toHaveTextContent(/waiting|collecting|investigat/i);
    expect(screen.queryByRole("region", { name: "Investigation report" })).not.toBeInTheDocument();

    await act(async () => {
      resolve(report);
      await pending;
    });
    expect(screen.getByText("Report received")).toBeVisible();
    expect(screen.queryByText("Awaiting response")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Evidence: 4 evidence items/ })).toBeVisible();
  });

  it("keeps the previous report and its selected tab during a new request, cancellation and failure", async () => {
    let resolve!: (value: InvestigationReport) => void;
    const pending = new Promise<InvestigationReport>((complete) => {
      resolve = complete;
    });
    createMock
      .mockResolvedValueOnce(report)
      .mockReturnValueOnce(pending)
      .mockRejectedValueOnce(new ApiError("Could not connect to the investigator API."));
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: "Investigate" }));
    const previous = await screen.findByRole("region", { name: "Investigation report" });
    await user.click(within(previous).getByRole("button", { name: "Data gaps (1)" }));
    expect(within(previous).getByText("Traces unavailable.")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Investigate" }));
    expect(screen.getByRole("region", { name: "Investigation report" })).toBe(previous);
    expect(
      screen.getByText("Showing the previous report while the new investigation runs."),
    ).toBeVisible();
    expect(within(previous).getByRole("button", { name: "Data gaps (1)" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(previous).getByText("Traces unavailable.")).toBeVisible();
    expect(scrollMock).not.toHaveBeenCalled();
    expect(screen.getByRole("region", { name: "Evidence flow" })).not.toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Stop waiting" }));
    expect(createMock.mock.calls[1]?.[1].aborted).toBe(true);
    expect(screen.getByRole("region", { name: "Investigation report" })).toBe(previous);
    expect(
      screen.getByText("Investigation stopped. Showing the last received report."),
    ).toBeVisible();

    await act(async () => {
      resolve({ ...report, summary: "Discard this cancelled response." });
      await pending;
    });
    expect(screen.queryByText("Discard this cancelled response.")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Investigation report" })).toBe(previous);

    await user.click(screen.getByRole("button", { name: "Investigate" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not connect to the investigator API.",
    );
    expect(screen.getByRole("region", { name: "Investigation report" })).toBe(previous);
    expect(
      screen.getByText("The new investigation failed. Showing the last received report."),
    ).toBeVisible();
    expect(within(previous).getByRole("button", { name: "Data gaps (1)" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(previous).getByText("Traces unavailable.")).toBeVisible();
    expect(scrollMock).not.toHaveBeenCalled();
  });

  it("rejects an invalid time window locally, announces it and focuses the invalid field", async () => {
    const user = userEvent.setup();
    render(<App />);
    const start = screen.getByLabelText("From");
    const end = screen.getByLabelText("Until (excluded)");
    fireEvent.change(start, { target: { value: "2026-10-14T10:00" } });
    fireEvent.change(end, { target: { value: "2026-10-14T10:00" } });
    await user.click(screen.getByRole("button", { name: "Investigate" }));

    expect(createMock).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/check|correct|end|after|later/i);
    expect(end).toHaveFocus();
    expect(end).toHaveAttribute("aria-invalid", "true");
    expect(scrollMock).not.toHaveBeenCalled();
  });
});
