import { expect, test } from "@playwright/test";
import { historyItem, investigationReport, savedId, savedInvestigation } from "./fixtures";

test("opens a saved report after creation, reloads its URL and never repeats analysis", async ({
  page,
}) => {
  let posts = 0;
  await page.route("**/api/investigations", (route) => {
    expect(route.request().method()).toBe("POST");
    posts++;
    return route.fulfill({ json: investigationReport, headers: { "X-Investigation-ID": savedId } });
  });
  await page.route(`**/api/investigations/${savedId}`, (route) =>
    route.fulfill({ json: savedInvestigation }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Investigate", exact: true }).click();
  await page.getByRole("link", { name: "Open saved investigation →" }).click();
  await expect(page).toHaveURL(new RegExp(`/investigations/${savedId}$`));
  await expect(
    page.getByRole("heading", { name: "Saved investigation", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("region", { name: "Saved metadata" })).toContainText("fixture-model");
  await expect(page.getByRole("region", { name: "Investigation report" })).toContainText(
    investigationReport.summary,
  );
  const back = await page.getByRole("link", { name: "← Back to investigations" }).boundingBox();
  const title = await page
    .getByRole("heading", { name: "Saved investigation", exact: true })
    .boundingBox();
  expect(back).not.toBeNull();
  expect(title).not.toBeNull();
  expect(title!.y - (back!.y + back!.height)).toBeGreaterThanOrEqual(16);
  await page.reload();
  await expect(page.getByRole("region", { name: "Saved metadata" })).toContainText(savedId);
  await expect(page.getByRole("button", { name: /^Logs:/ })).toContainText("Not recorded");
  await page.getByRole("button", { name: "Copy report link" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: /Link copied|Copy the address/ }),
  ).toBeVisible();
  expect(posts).toBe(1);
});

test("preserves recorded collection durations when reopening a saved report", async ({ page }) => {
  const report: typeof investigationReport = {
    ...investigationReport,
    source_collections: [
      {
        source: "log",
        status: "collected",
        evidence_count: 1,
        duration_ms: 42,
        issues: [],
      },
      {
        source: "metric",
        status: "partial",
        evidence_count: 1,
        duration_ms: 1300,
        issues: ["Some queries failed."],
      },
      {
        source: "actuator",
        status: "collected",
        evidence_count: 1,
        duration_ms: 7,
        issues: ["Actuator is a current snapshot."],
      },
    ],
  };
  let reads = 0;
  await page.route("**/api/**", (route) => {
    expect(route.request().method()).toBe("GET");
    expect(new URL(route.request().url()).pathname).toBe(`/api/investigations/${savedId}`);
    reads++;
    return route.fulfill({ json: { ...savedInvestigation, report } });
  });
  await page.goto(`/investigations/${savedId}`);
  await expect(page.getByRole("button", { name: /^Logs:/ })).toContainText("Collected · 42 ms");
  await expect(page.getByRole("button", { name: /^Metrics:/ })).toContainText("Partial · 1,300 ms");
  await page.reload();
  await expect(page.getByRole("button", { name: /^Logs:/ })).toContainText("Collected · 42 ms");
  expect(reads).toBe(2);
});

test("keeps filters and pages in URLs, restores them on return and validates date ranges", async ({
  page,
}) => {
  const queries: string[] = [];
  await page.route(/\/api\/investigations(?:\?.*)?$/, (route) => {
    const url = new URL(route.request().url());
    queries.push(url.search);
    const older = url.searchParams.has("cursor");
    return route.fulfill({
      json: {
        items: [{ ...historyItem, summary: older ? "Older report" : "Newest report" }],
        next_cursor: older ? null : "opaque-cursor",
      },
    });
  });
  await page.route(`**/api/investigations/${savedId}`, (route) =>
    route.fulfill({ json: savedInvestigation }),
  );
  await page.goto("/investigations?service=order-service&environment=local");
  await expect(page.getByText("Newest report", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Older investigations →" }).click();
  await expect(page.getByText("Older report", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/cursor=opaque-cursor/);
  await page.getByRole("link", { name: `Open investigation ${savedId}` }).click();
  await expect(page.getByRole("region", { name: "Investigation report" })).toBeVisible();
  await page.getByRole("link", { name: "← Back to investigations" }).click();
  await expect(page.getByText("Older report", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Newest results" }).click();
  await expect(page.getByText("Newest report", { exact: true })).toBeVisible();
  await page.getByLabel("Created from", { exact: true }).fill("2026-10-20T12:00");
  await page.getByLabel("Created until (excluded)", { exact: true }).fill("2026-10-20T11:00");
  const before = queries.length;
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByRole("alert")).toContainText("must be after");
  expect(queries).toHaveLength(before);
  await page.getByLabel("Created until (excluded)", { exact: true }).fill("2026-10-21T12:00");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/created_from=2026-10-20T12%3A00%3A00.000Z/);
  await expect.poll(() => queries.at(-1)).toContain("created_from=");
  await expect(page.getByText("Newest report", { exact: true })).toBeVisible();
  expect(queries.at(-1)).not.toContain("cursor");
  await page.goBack();
  await expect(page).not.toHaveURL(/created_from=/);
  await expect(page.getByLabel("Created from", { exact: true })).toHaveValue("");
  await page.getByRole("link", { name: "Reset filters" }).click();
  await expect(page.getByText("Newest report", { exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Service", exact: true })).toHaveText(
    "All services",
  );
  await page.getByRole("combobox", { name: "Service", exact: true }).click();
  await page.getByRole("option", { name: "order-service", exact: true }).click();
  await page.getByRole("link", { name: "Reset filters" }).click();
  await expect(page.getByRole("combobox", { name: "Service", exact: true })).toHaveText(
    "All services",
  );
});

test("offers retry for unavailable storage and a useful empty history", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/investigations", (route) => {
    calls++;
    return calls === 1
      ? route.fulfill({ status: 503, json: { detail: "private DB error" } })
      : route.fulfill({ json: { items: [], next_cursor: null } });
  });
  await page.goto("/investigations");
  await expect(page.getByRole("alert")).toContainText("PostgreSQL");
  await expect(page.getByRole("alert")).not.toContainText("private");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { name: "No saved investigations" })).toBeVisible();
  await page.getByRole("link", { name: "New investigation", exact: true }).last().click();
  await expect(page.getByRole("button", { name: "Investigate", exact: true })).toBeVisible();
});

test("handles a missing saved report, invalid UUID and unknown page without a crash", async ({
  page,
}) => {
  await page.route(`**/api/investigations/${savedId}`, (route) =>
    route.fulfill({ status: 404, json: { detail: "Not found" } }),
  );
  await page.goto(`/investigations/${savedId}`);
  await expect(page.getByRole("alert")).toHaveText("This saved investigation was not found.");
  await page.goto("/investigations/not-a-uuid");
  await expect(page.getByRole("alert")).toHaveText("This saved investigation link is invalid.");
  await page.goto("/unknown-page");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
});

test("renders small-screen history without body overflow and escapes report text", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/investigations", (route) =>
    route.fulfill({
      json: {
        items: [{ ...historyItem, summary: '<script>alert("unsafe")</script>' }],
        next_cursor: null,
      },
    }),
  );
  await page.goto("/investigations");
  await expect(page.getByRole("table")).toContainText('<script>alert("unsafe")</script>');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await expect(
    page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("link", { name: "≡ Investigations" }),
  ).toHaveAttribute("aria-current", "page");
});

test("history selectors float above the form, keep one menu open and apply selected filters", async ({
  page,
}) => {
  const queries: string[] = [];
  await page.route(/\/api\/investigations(?:\?.*)?$/, (route) => {
    queries.push(new URL(route.request().url()).search);
    return route.fulfill({
      json: {
        items: [
          historyItem,
          {
            ...historyItem,
            id: "de6351fb-ce43-435f-bb61-b489c234a132",
            service: "payment-service",
            environment: "staging",
          },
        ],
        next_cursor: null,
      },
    });
  });
  await page.goto("/investigations");
  await expect(page.getByRole("table")).toBeVisible();
  const service = page.getByRole("combobox", { name: "Service", exact: true });
  const environment = page.getByRole("combobox", { name: "Environment", exact: true });
  const dates = page.getByLabel("Created from", { exact: true });
  const before = await dates.boundingBox();
  await service.press("Enter");
  await expect(page.getByRole("listbox")).toHaveCount(1);
  await expect(
    page.getByRole("combobox", { name: "Environment", exact: true, includeHidden: true }),
  ).toBeDisabled();
  await expect(page.getByRole("option", { name: "All services", exact: true })).toBeVisible();
  await expect(page.getByRole("option", { name: "payment-service", exact: true })).toBeVisible();
  expect(await dates.boundingBox()).toEqual(before);
  await page.keyboard.press("Escape");
  await expect(service).toBeFocused();
  await expect(service).toHaveText("All services");
  await service.click();
  await page.getByRole("option", { name: "payment-service", exact: true }).click();
  await environment.click();
  await page.getByRole("option", { name: "staging", exact: true }).click();
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect.poll(() => queries.at(-1)).toContain("service=payment-service&environment=staging");
  await expect(service).toHaveText("payment-service");
  await page.reload();
  await expect(service).toHaveText("payment-service");
  await expect(environment).toHaveText("staging");
  const style = await dates.evaluate((input) => {
    const css = getComputedStyle(input);
    return {
      height: css.height,
      fontSize: css.fontSize,
      fontWeight: css.fontWeight,
      padding: css.padding,
      borderRadius: css.borderRadius,
      background: css.backgroundColor,
    };
  });
  expect(style.fontWeight).toBe("400");
  expect(await service.evaluate((element) => getComputedStyle(element).fontWeight)).toBe("400");
  await page.goto("/");
  const mainStyle = await page.getByLabel("From", { exact: true }).evaluate((input) => {
    const css = getComputedStyle(input);
    return {
      height: css.height,
      fontSize: css.fontSize,
      fontWeight: css.fontWeight,
      padding: css.padding,
      borderRadius: css.borderRadius,
      background: css.backgroundColor,
    };
  });
  expect(style).toEqual(mainStyle);
});
