import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import App from "../../App";
import { ApiError } from "../../api/client";
import { getUsage, usageDashboardSchema } from "../../api/usage";
import { dollars } from "./presentation";

vi.mock("../../api/usage", async (original) => ({
  ...(await original<typeof import("../../api/usage")>()),
  getUsage: vi.fn(),
}));
const data = usageDashboardSchema.parse({
  generated_at: "2026-10-21T12:00:00Z",
  start_time: "2026-10-15T00:00:00Z",
  end_time: "2026-10-21T12:00:00Z",
  totals: {
    calls: 2,
    reported_calls: 1,
    priced_calls: 1,
    input_tokens: 1000,
    cached_input_tokens: 400,
    output_tokens: 100,
    total_tokens: 1100,
    estimated_cost_usd: "0.00044",
  },
  daily: [
    {
      day: "2026-10-21",
      calls: 2,
      reported_calls: 1,
      priced_calls: 1,
      input_tokens: 1000,
      cached_input_tokens: 400,
      output_tokens: 100,
      total_tokens: 1100,
      estimated_cost_usd: "0.00044",
    },
  ],
  largest: [
    {
      investigation_id: "d88ba75f-2b7e-4aaf-b81d-3aaf21330bc2",
      service: "order-service",
      environment: "local",
      started_at: "2026-10-21T11:00:00Z",
      duration_ms: 1200,
      total_tokens: 1100,
      estimated_cost_usd: "0.00044",
    },
  ],
});
const mock = vi.mocked(getUsage);
beforeEach(() => {
  window.history.replaceState({}, "", "/usage");
  mock.mockReset();
  vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
});

it("shows a compact overview, chart and links to the largest analyses", async () => {
  mock.mockResolvedValue(data);
  const user = userEvent.setup();
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Usage over time" })).toBeVisible();
  expect(screen.getByRole("navigation", { name: "Main navigation" })).toContainElement(
    screen.getByRole("link", { name: /Usage/ }),
  );
  const chart = screen.getByRole("region", { name: "Daily usage" });
  expect(screen.getByText(/1 of 2 calls reported/)).toBeVisible();
  expect(within(chart).getByRole("button", { name: /2026-10-21:.*missing data/ })).toBeVisible();
  await user.click(within(chart).getByRole("button", { name: "Tokens" }));
  expect(within(chart).getByRole("button", { name: /2026-10-21: 1,100/ })).toBeVisible();
  expect(screen.getByRole("link", { name: "order-service →" })).toHaveAttribute(
    "href",
    `/investigations/${data.largest[0]?.investigation_id}`,
  );
  await user.click(screen.getByRole("button", { name: "Last 30 days" }));
  expect(mock).toHaveBeenLastCalledWith(30, "tokens", expect.any(AbortSignal));
  await screen.findByRole("heading", { name: "Largest analyses" });
  await user.click(
    within(screen.getByRole("region", { name: "Largest analyses" })).getByRole("button", {
      name: "Time",
    }),
  );
  expect(mock).toHaveBeenLastCalledWith(30, "duration", expect.any(AbortSignal));
});

it("distinguishes missing usage from zero", async () => {
  mock.mockResolvedValue({
    ...data,
    totals: {
      ...data.totals,
      priced_calls: 0,
      reported_calls: 0,
      estimated_cost_usd: "0",
      input_tokens: 0,
      cached_input_tokens: 0,
      output_tokens: 0,
      total_tokens: 0,
    },
  });
  render(<App />);
  expect(await screen.findAllByText("Not available")).toHaveLength(2);
  expect(screen.getByText("Token counts were not returned")).toBeVisible();
  expect(screen.queryByText(/0 input/)).not.toBeInTheDocument();
});

it("offers a retry after storage fails", async () => {
  mock.mockRejectedValueOnce(new ApiError("Usage storage unavailable")).mockResolvedValue(data);
  const user = userEvent.setup();
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Usage storage unavailable");
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByRole("heading", { name: "Usage over time" })).toBeVisible();
});

it("shows a useful empty state without fabricated bars", async () => {
  mock.mockResolvedValue({
    ...data,
    totals: {
      ...data.totals,
      calls: 0,
      reported_calls: 0,
      priced_calls: 0,
      input_tokens: 0,
      cached_input_tokens: 0,
      output_tokens: 0,
      total_tokens: 0,
      estimated_cost_usd: "0",
    },
    largest: [],
  });
  render(<App />);
  expect(await screen.findByRole("heading", { name: "No recorded model calls" })).toBeVisible();
  expect(screen.queryByRole("region", { name: "Daily usage" })).not.toBeInTheDocument();
});

it("does not round a small positive charge to free", () => {
  expect(dollars("0.0000001")).toBe("< $0.000001");
  expect(dollars(null)).toBe("Not available");
});
