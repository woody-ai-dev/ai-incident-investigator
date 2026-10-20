import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { InvestigationReport } from "../../api/contracts";
import { SourceFlow } from "./SourceFlow";

beforeEach(() => {
  // jsdom does not track :focus-visible across keyboard transitions. Pointer events still
  // determine mouse focus in the component; model only the focused-element match here.
  const matches = HTMLElement.prototype.matches;
  vi.spyOn(HTMLElement.prototype, "matches").mockImplementation(function (
    this: HTMLElement,
    selector,
  ) {
    return selector === ":focus-visible"
      ? this === document.activeElement
      : matches.call(this, selector);
  });
});

const report: InvestigationReport = {
  analysis_status: "failed",
  summary: "Collected evidence retained after analysis failed.",
  evidence: [
    {
      id: "log-1",
      source: "log",
      service: "order-service",
      summary: "Order received.",
      reference: "local-jsonl:line:1",
      start_time: "2026-10-02T19:01:00Z",
      end_time: null,
    },
    {
      id: "log-2",
      source: "log",
      service: "order-service",
      summary: "Payment timed out.",
      reference: "local-jsonl:line:2",
      start_time: "2026-10-02T19:01:05Z",
      end_time: null,
    },
    {
      id: "actuator-health",
      source: "actuator",
      service: "order-service",
      summary: "Current health UP.",
      reference: "fixture:health",
      start_time: "2026-10-02T20:00:00Z",
      end_time: null,
    },
  ],
  findings: [],
  hypotheses: [],
  recommended_checks: [],
  missing_data: ["Prometheus evidence is unavailable.", "LLM analysis failed."],
};

it("highlights the hovered graph source and its connections with honest context", async () => {
  const user = userEvent.setup();
  const { container } = render(<SourceFlow phase="success" report={report} />);
  const logs = container.querySelector('g[data-source="log"]')!;
  await user.hover(logs);
  expect(container.querySelector('path[data-source="log"]')).toHaveAttribute("data-active", "true");
  expect(container.querySelector('path[data-source="report"]')).toHaveAttribute(
    "data-active",
    "true",
  );
  expect(container.querySelector('path[data-source="metric"]')).toHaveAttribute(
    "data-active",
    "false",
  );
  expect(within(screen.getByRole("note")).getByText(/Historical JSONL records/)).toBeVisible();
  await user.unhover(logs);
  expect(container.querySelector('path[data-source="log"]')).toHaveAttribute(
    "data-active",
    "false",
  );
});

it("keeps keyboard highlighting until focus moves and clears it after the last source", async () => {
  const user = userEvent.setup();
  const { container } = render(<SourceFlow phase="success" report={report} />);
  await user.hover(container.querySelector('g[data-source="actuator"]')!);
  await user.tab();
  const logs = screen.getByRole("button", { name: /^Logs:/ });
  expect(logs).toHaveFocus();
  expect(logs).toHaveAttribute("data-focus-visible", "true");
  const actuatorNode = container.querySelector('g[data-source="actuator"]')!;
  await user.hover(actuatorNode);
  expect(logs).toHaveAttribute("data-focus-visible", "true");
  await user.unhover(actuatorNode);
  expect(container.querySelector('path[data-source="log"]')).toHaveAttribute("data-active", "true");
  await user.tab();
  const metrics = screen.getByRole("button", { name: /^Metrics:/ });
  expect(metrics).toHaveFocus();
  expect(container.querySelector('path[data-source="metric"]')).toHaveAttribute(
    "data-active",
    "true",
  );
  expect(
    within(screen.getByRole("note")).getByText(/Aggregated metrics do not identify/),
  ).toBeVisible();
  await user.keyboard("{Enter}");
  expect(container.querySelector('path[data-source="metric"]')).toHaveAttribute(
    "data-active",
    "true",
  );
  expect(metrics).not.toHaveAttribute("aria-pressed");
  await user.tab();
  expect(screen.getByRole("button", { name: /^Actuator:/ })).toHaveFocus();
  expect(container.querySelector('path[data-source="metric"]')).toHaveAttribute(
    "data-active",
    "false",
  );
  await user.tab();
  expect(container.querySelectorAll('path[data-active="true"]')).toHaveLength(0);
  expect(within(screen.getByRole("note")).getByText("Explore the sources")).toBeVisible();
});

it("keeps actual counts and analysis status separate from source availability", () => {
  const { rerender } = render(<SourceFlow phase="success" report={report} />);
  expect(screen.getByRole("button", { name: /^Logs: 2 evidence items/ })).toBeVisible();
  expect(screen.getByRole("button", { name: /^Metrics: No evidence/ })).toBeVisible();
  expect(screen.getByRole("button", { name: /^Actuator: 1 evidence item/ })).toBeVisible();
  expect(screen.getByRole("img")).toHaveAttribute(
    "aria-label",
    expect.stringContaining("LLM failed"),
  );
  expect(screen.getByText(/does not mean a source is offline/)).toBeVisible();
  rerender(<SourceFlow phase="error" report={report} />);
  expect(screen.getByRole("button", { name: /^Logs: No report/ })).toBeVisible();
  expect(screen.getByText(/source availability cannot be inferred/)).toBeVisible();
});

it("clears graph highlighting after a clicked node loses pointer hover", async () => {
  const user = userEvent.setup();
  const { container } = render(<SourceFlow phase="success" report={report} />);
  const logs = container.querySelector('g[data-source="log"]')!;
  await user.click(logs);
  expect(container.querySelector('path[data-source="log"]')).toHaveAttribute("data-active", "true");
  await user.unhover(logs);
  expect(container.querySelectorAll('path[data-active="true"]')).toHaveLength(0);
  expect(within(screen.getByRole("note")).getByText("Explore the sources")).toBeVisible();
});

it("allows keyboard inspection after clicking a graph node and tabbing in from outside", async () => {
  const user = userEvent.setup();
  const { container } = render(
    <>
      <button type="button">Before the graph</button>
      <SourceFlow phase="success" report={report} />
    </>,
  );
  const logsNode = container.querySelector('g[data-source="log"]')!;
  await user.click(logsNode);
  await user.unhover(logsNode);
  expect(container.querySelectorAll('path[data-active="true"]')).toHaveLength(0);
  await user.tab();
  expect(screen.getByRole("button", { name: "Before the graph" })).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("button", { name: /^Logs:/ })).toHaveFocus();
  expect(container.querySelector('path[data-source="log"]')).toHaveAttribute("data-active", "true");
  expect(within(screen.getByRole("note")).getByText(/Historical JSONL records/)).toBeVisible();
});

it("clears mouse highlighting after clicking a source button even while it retains DOM focus", async () => {
  const user = userEvent.setup();
  const { container } = render(<SourceFlow phase="success" report={report} />);
  const logs = screen.getByRole("button", { name: /^Logs:/ });
  await user.click(logs);
  expect(logs).toHaveFocus();
  expect(container.querySelector('path[data-source="log"]')).toHaveAttribute("data-active", "true");
  await user.unhover(logs);
  expect(logs).toHaveFocus();
  expect(container.querySelectorAll('path[data-active="true"]')).toHaveLength(0);
  expect(logs).not.toHaveAttribute("aria-pressed");
  expect(within(screen.getByRole("note")).getByText("Explore the sources")).toBeVisible();
  await user.tab();
  const metrics = screen.getByRole("button", { name: /^Metrics:/ });
  expect(metrics).toHaveFocus();
  expect(container.querySelector('path[data-source="metric"]')).toHaveAttribute(
    "data-active",
    "true",
  );
});

it("clears the keyboard focus ring after a mouse click on the same button without moving focus", async () => {
  const user = userEvent.setup();
  const { container } = render(<SourceFlow phase="success" report={report} />);
  const logs = screen.getByRole("button", { name: /^Logs:/ });
  await user.tab();
  expect(logs).toHaveFocus();
  expect(logs).toHaveAttribute("data-focus-visible", "true");
  await user.click(logs);
  await user.unhover(logs);
  expect(logs).toHaveFocus();
  expect(logs).toHaveAttribute("data-focus-visible", "false");
  expect(container.querySelectorAll('path[data-active="true"]')).toHaveLength(0);
  expect(within(screen.getByRole("note")).getByText("Explore the sources")).toBeVisible();
  await user.keyboard("{Enter}");
  expect(logs).toHaveFocus();
  expect(logs).toHaveAttribute("data-focus-visible", "true");
});

it("keeps source context available after a touch tap until focus leaves the button", async () => {
  const user = userEvent.setup();
  const { container } = render(
    <>
      <SourceFlow phase="success" report={report} />
      <button type="button">Outside the graph</button>
    </>,
  );
  const logs = screen.getByRole("button", { name: /^Logs:/ });
  await user.pointer([
    { keys: "[TouchA>]", target: logs },
    { keys: "[/TouchA]", target: logs },
  ]);
  fireEvent.pointerLeave(logs, { pointerType: "touch" });
  expect(logs).toHaveFocus();
  expect(container.querySelector('path[data-source="log"]')).toHaveAttribute("data-active", "true");
  expect(within(screen.getByRole("note")).getByText(/Historical JSONL records/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Outside the graph" }));
  expect(container.querySelectorAll('path[data-active="true"]')).toHaveLength(0);
  expect(within(screen.getByRole("note")).getByText("Explore the sources")).toBeVisible();
});

it("shows returned evidence signals even for an immediate response and replays a new report", () => {
  const { container, rerender } = render(<SourceFlow phase="success" report={report} />);
  expect(screen.getByText("Report received")).toBeVisible();
  expect(container.querySelector('[data-flow-signal="received"]')).toBeInTheDocument();
  expect(container.querySelector('[data-signal-source="log"]')).toBeInTheDocument();
  expect(container.querySelector('[data-signal-source="actuator"]')).toBeInTheDocument();
  expect(container.querySelector('[data-signal-source="metric"]')).not.toBeInTheDocument();
  expect(container.querySelector('g[data-source="metric"] circle')).toHaveAttribute(
    "data-empty",
    "true",
  );
  const previousSignal = container.querySelector('[data-flow-signal="received"]');
  rerender(<SourceFlow phase="success" report={{ ...report }} />);
  expect(container.querySelector('[data-flow-signal="received"]')).not.toBe(previousSignal);
});

it("distinguishes actual waiting from the finite receipt signal", () => {
  const { container, rerender } = render(<SourceFlow phase="loading" />);
  expect(screen.getByText(/pending request, not individual source progress/)).toBeVisible();
  expect(container.querySelector('[data-flow-signal="pending"]')).toBeInTheDocument();
  expect(container.querySelectorAll("[data-signal-source]")).toHaveLength(4);
  rerender(<SourceFlow phase="success" report={report} />);
  expect(container.querySelector('[data-flow-signal="pending"]')).not.toBeInTheDocument();
  expect(container.querySelector('[data-flow-signal="received"]')).toBeInTheDocument();
  expect(screen.getByText(/signal highlights the returned evidence/)).toBeVisible();
  rerender(<SourceFlow phase="error" />);
  expect(container.querySelector("[data-flow-signal]")).not.toBeInTheDocument();
});
