import { expect, test } from "@playwright/test";

const totals = {
  calls: 1,
  reported_calls: 1,
  priced_calls: 1,
  input_tokens: 1000,
  cached_input_tokens: 400,
  output_tokens: 100,
  total_tokens: 1100,
  estimated_cost_usd: "0.00044",
};
const dashboard = {
  generated_at: "2026-10-21T12:00:00Z",
  start_time: "2026-10-15T00:00:00Z",
  end_time: "2026-10-21T12:00:00Z",
  totals,
  daily: [{ day: "2026-10-21", ...totals }],
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
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/usage?*", (route) => route.fulfill({ json: dashboard }));
});

test("bars grow from the bottom without moving the layout", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/usage");
  const day = page.getByRole("button", { name: /2026-10-21:/ });
  await expect(day).toBeVisible();
  const heights = await day
    .locator("span")
    .first()
    .evaluate((bar) => {
      const animation = bar.getAnimations()[0];
      if (!animation) throw new Error("Usage bar must animate on entry");
      animation.pause();
      const states = [0, 325, 650].map((time) => {
        animation.currentTime = time;
        const rect = bar.getBoundingClientRect();
        return { height: rect.height, bottom: rect.bottom };
      });
      return states;
    });
  expect(heights[0]?.height).toBe(0);
  expect(heights[1]?.height).toBeGreaterThan(0);
  expect(heights[2]?.height).toBeGreaterThan(heights[1]?.height ?? 0);
  expect(heights[0]?.bottom).toBeCloseTo(heights[2]?.bottom ?? 0, 1);
  await day.focus();
  await expect(day.getByRole("tooltip")).toBeVisible();
  await page.getByRole("link", { name: "New investigation", exact: false }).first().click();
  await page.getByRole("link", { name: "Usage", exact: false }).click();
  await expect(page.getByRole("heading", { name: "Usage over time" })).toBeVisible();
});

test("respects reduced motion and keeps the mobile page within the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/usage");
  const day = page.getByRole("button", { name: /2026-10-21:/ });
  await expect(day).toBeVisible();
  expect(
    await day
      .locator("span")
      .first()
      .evaluate((bar) => bar.getAnimations().length),
  ).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole("link", { name: "order-service →" })).toBeVisible();
});

test("keeps a full month and its focused tooltips inside the mobile viewport", async ({ page }) => {
  const daily = Array.from({ length: 30 }, (_, index) => ({
    day: new Date(Date.UTC(2026, 8, 22 + index)).toISOString().slice(0, 10),
    ...totals,
  }));
  await page.route("**/api/usage?*", (route) => route.fulfill({ json: { ...dashboard, daily } }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/usage");
  await page.getByRole("button", { name: "Last 30 days", exact: true }).click();
  const chart = page.getByRole("region", { name: "Daily usage" });
  await expect(chart.getByRole("button", { name: /2026-10-21:/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  for (const index of [0, 14, 28, 29]) {
    const day = chart.getByRole("button", { name: /2026-\d{2}-\d{2}:/ }).nth(index);
    await day.focus();
    const tooltip = day.getByRole("tooltip");
    await expect(tooltip).toBeVisible();
    const bounds = await tooltip.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
});
