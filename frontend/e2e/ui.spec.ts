import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { investigationReport, investigationRequest } from "./fixtures";

async function investigate(page: Page) {
  await page.getByLabel("From", { exact: true }).fill("2026-10-02T19:00");
  await page.getByLabel("Until (excluded)", { exact: true }).fill("2026-10-02T19:15");
  await page.getByLabel("What happened? Optional").fill(investigationRequest.description ?? "");
  const posted = page.waitForRequest("**/api/investigations");
  await page.getByRole("button", { name: "Investigate", exact: true }).click();
  expect((await posted).postDataJSON()).toEqual(investigationRequest);
  await expect(page.getByRole("region", { name: "Investigation report" })).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/investigations", async (route) => {
    if (route.request().method() !== "POST") return route.abort();
    await route.fulfill({ status: 200, json: investigationReport });
  });
  await page.goto("/");
});

test("navigates report evidence and downloads the full JSON export", async ({ page }, testInfo) => {
  await investigate(page);
  const report = page.getByRole("region", { name: "Investigation report" });
  const details = report.getByRole("complementary", {
    name: "Evidence details",
  });
  const observation = report.getByRole("button", {
    name: /Payment request timed out/,
  });
  await observation.click();
  await expect(details).toBeFocused();
  await expect(details).toBeInViewport();
  await expect(details.getByText("local-jsonl:line:42", { exact: true })).toBeVisible();
  await expect(details).toContainText("19:01:05.123456 UTC");
  await details.getByRole("button", { name: "Close", exact: true }).click();
  await expect(observation).toBeFocused();

  await report.getByRole("button", { name: "Analysis & checks", exact: true }).click();
  await expect(report.getByText("A payment timeout was recorded.", { exact: true })).toBeVisible();
  const hypothesis = report
    .locator("article")
    .filter({ hasText: "A payment dependency may be slow." });
  const reference = hypothesis.getByRole("button", {
    name: "metric-errors",
    exact: true,
  });
  await reference.press("Enter");
  await expect(details).toBeFocused();
  await expect(details.getByRole("heading", { name: "metric-errors", exact: true })).toBeVisible();
  await expect(
    details.getByText(
      "http://prometheus:9090/api/v1/query_range?query=http_server_requests_seconds_count",
      { exact: true },
    ),
  ).toBeVisible();
  await details.getByRole("button", { name: "Close", exact: true }).click();
  await expect(reference).toBeFocused();
  await expect(report.getByText("Inspect payment latency.", { exact: true })).toBeVisible();
  await report.getByRole("button", { name: "Data gaps (2)", exact: true }).click();
  await expect(
    report.getByText("Distributed traces were not available.", { exact: true }),
  ).toBeVisible();
  await report.getByRole("button", { name: "Evidence (3)", exact: true }).click();
  await expect(observation).toBeVisible();

  const downloaded = page.waitForEvent("download");
  await report.getByRole("button", { name: "Export JSON", exact: true }).click();
  const download = await downloaded;
  expect(download.suggestedFilename()).toBe("investigation-report.json");
  const path = testInfo.outputPath(download.suggestedFilename());
  await download.saveAs(path);
  const exported: unknown = JSON.parse(await readFile(path, "utf8"));
  expect(exported).toEqual({
    schema_version: 1,
    request: investigationRequest,
    report: investigationReport,
  });
});

test("keeps the last successful report available after a subsequent HTTP 500", async ({ page }) => {
  await investigate(page);
  await page.getByLabel("What happened? Optional").fill("Retry the investigation.");
  await page.route("**/api/investigations", (route) =>
    route.fulfill({ status: 500, json: { detail: "Offline fixture failure" } }),
  );
  await page.getByRole("button", { name: "Investigate", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("The investigation API returned HTTP 500.");
  await expect(
    page.getByRole("status").filter({
      hasText: "The new investigation failed. Showing the last received report.",
    }),
  ).toBeVisible();
  const report = page.getByRole("region", { name: "Investigation report" });
  await expect(report.getByText(investigationReport.summary, { exact: true })).toBeVisible();
  await report.getByRole("button", { name: /Payment request timed out/ }).click();
  await expect(report.getByRole("complementary", { name: "Evidence details" })).toContainText(
    "local-jsonl:line:42",
  );
  await expect(
    page
      .getByRole("region", { name: "Evidence flow" })
      .getByRole("button", { name: /^Logs: No report/ }),
  ).toBeVisible();
});

test("closes dropdowns with Escape without changing selection or moving the layout", async ({
  page,
}) => {
  const form = page.locator("form");
  const flow = page.getByRole("region", { name: "Evidence flow", includeHidden: true });
  const formBounds = await form.boundingBox();
  const flowBounds = await flow.boundingBox();
  expect(formBounds).not.toBeNull();
  expect(flowBounds).not.toBeNull();

  for (const [label, option, other] of [
    ["Service", "order-service", "Environment"],
    ["Environment", "local", "Service"],
  ] as const) {
    const trigger = page.getByRole("combobox", { name: label, exact: true });
    const otherTrigger = page.getByRole("combobox", {
      name: other,
      exact: true,
      includeHidden: true,
    });
    await trigger.press("Enter");
    await expect(page.getByRole("listbox")).toBeVisible();
    await expect(page.getByRole("option", { name: option, exact: true })).toBeVisible();
    await expect(page.getByRole("listbox")).toHaveCount(1);
    await expect(otherTrigger).toBeDisabled();
    expect(await form.boundingBox()).toEqual(formBounds);
    expect(await flow.boundingBox()).toEqual(flowBounds);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("listbox")).toBeHidden();
    await expect(trigger).toBeFocused();
    await expect(trigger).toContainText(option);
    await expect(otherTrigger).toBeEnabled();
    expect(await form.boundingBox()).toEqual(formBounds);
    expect(await flow.boundingBox()).toEqual(flowBounds);
  }
});

test("clears mouse highlights while preserving native keyboard inspection", async ({ page }) => {
  const flow = page.getByRole("region", { name: "Evidence flow" });
  const logs = flow.getByRole("button", { name: /^Logs:/ });
  const metrics = flow.getByRole("button", { name: /^Metrics:/ });
  const context = flow.getByRole("note", { name: "Source context" });
  await logs.click();
  await expect(logs).toBeFocused();
  await expect(flow.locator('path[data-source="log"]')).toHaveAttribute("data-active", "true");
  await page.getByRole("heading", { name: "Understand what happened.", exact: true }).hover();
  await expect(logs).toBeFocused();
  await expect(logs).toHaveAttribute("data-focus-visible", "false");
  await expect(logs).toHaveCSS("outline-style", "none");
  await expect(flow.locator('path[data-active="true"]')).toHaveCount(0);
  await expect(context).toContainText("Explore the sources");

  await page.keyboard.press("Tab");
  await expect(metrics).toBeFocused();
  await expect(metrics).toHaveAttribute("data-focus-visible", "true");
  await expect(metrics).toHaveCSS("outline-style", "solid");
  await expect(flow.locator('path[data-source="metric"]')).toHaveAttribute("data-active", "true");
  await expect(context).toContainText("Aggregated metrics do not identify an individual request.");
  await metrics.press("Enter");
  await expect(metrics).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(flow.getByRole("button", { name: /^Actuator:/ })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(flow.locator('path[data-active="true"]')).toHaveCount(0);
  await expect(context).toContainText("Explore the sources");
});

test("report node reflects idle, pending, received, failed and stopped request states", async ({
  page,
}) => {
  const node = page.locator("rect[data-report-state]");
  await expect(node).toHaveAttribute("data-report-state", "empty");
  await expect(node).toHaveCSS("fill", "rgb(255, 255, 255)");
  let complete!: () => void;
  const pending = new Promise<void>((resolve) => {
    complete = resolve;
  });
  await page.route("**/api/investigations", async (route) => {
    await pending;
    await route.fulfill({ status: 200, json: investigationReport });
  });
  await page.getByRole("button", { name: "Investigate", exact: true }).click();
  await expect(node).toHaveAttribute("data-report-state", "pending");
  await expect(node).toHaveCSS("stroke", "rgb(168, 192, 246)");
  complete();
  await expect(node).toHaveAttribute("data-report-state", "received");
  await expect(node).toHaveCSS("fill", "rgb(240, 245, 255)");
  await page.route("**/api/investigations", (route) => route.fulfill({ status: 500 }));
  await page.getByRole("button", { name: "Investigate", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(node).toHaveAttribute("data-report-state", "empty");
  await expect(node).toHaveCSS("fill", "rgb(255, 255, 255)");
  let release!: () => void;
  const cancelled = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/investigations", async (route) => {
    await cancelled;
    await route.abort();
  });
  await page.getByRole("button", { name: "Investigate", exact: true }).click();
  await expect(node).toHaveAttribute("data-report-state", "pending");
  await page.getByRole("button", { name: "Stop waiting", exact: true }).click();
  await expect(node).toHaveAttribute("data-report-state", "empty");
  release();
});
