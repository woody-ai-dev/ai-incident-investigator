import { readFile, writeFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { z } from "zod";
import { reportSchema, requestSchema } from "../src/api/contracts";

// This file is excluded from ordinary UI/Compose suites. Only the opt-in config runs it.
test("a fresh incident is analyzed by a real model through the browser", async ({
  page,
  request,
}, testInfo) => {
  const recordDemo = process.env.RECORD_DEMO === "true";
  const pause = async (milliseconds: number) => {
    if (recordDemo) await page.waitForTimeout(milliseconds);
  };
  const browserErrors: string[] = [];
  let submissions = 0;
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("request", (sent) => {
    if (sent.method() === "POST" && new URL(sent.url()).pathname === "/api/investigations") {
      submissions += 1;
    }
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Understand what happened." })).toBeVisible();
  await pause(8_000);
  for (const label of ["Service", "Environment"]) {
    await page.getByRole("combobox", { name: label, exact: true }).click();
    await expect(page.getByRole("listbox")).toBeVisible();
    await pause(3_000);
    await page.keyboard.press("Escape");
  }

  const start = new Date(Date.now() - 30_000);
  const order = await request.post(
    new URL("/api/v1/orders", process.env.E2E_ORDERS_URL ?? "http://127.0.0.1:8081").href,
    { data: { productId: "book-1", quantity: 2 }, timeout: 10_000 },
  );
  expect(order.status()).toBe(504);
  const problem = z
    .object({ code: z.literal("PAYMENT_TIMEOUT"), orderId: z.uuid() })
    .parse(await order.json());
  await page
    .getByLabel("What happened?")
    .fill(
      `Order ${problem.orderId} failed with PAYMENT_TIMEOUT. Inspect the recorded failure and explain what is supported by the evidence.`,
    );
  // The demo scrapes every five seconds. Wait for fresh telemetry, without polling the model.
  await page.waitForTimeout(11_000);
  await page.getByLabel("From", { exact: true }).fill(start.toISOString().slice(0, 19));
  await page
    .getByLabel("Until (excluded)", { exact: true })
    .fill(new Date().toISOString().slice(0, 19));
  await pause(5_000);

  const result = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/investigations" &&
      response.request().method() === "POST",
    { timeout: 90_000 },
  );
  await page.getByRole("button", { name: "Investigate", exact: true }).click();
  const response = await result;
  expect(response.status()).toBe(200);
  const submitted = requestSchema.parse(response.request().postDataJSON());
  const report = reportSchema.parse(await response.json());
  await writeFile(
    testInfo.outputPath("live-investigation.json"),
    JSON.stringify({ order: problem, request: submitted, report }, null, 2),
  );
  expect(report.analysis_status).toBe("completed");
  expect(report.evidence.filter((item) => item.source === "metric")).toHaveLength(3);
  expect(report.evidence.filter((item) => item.source === "actuator")).toHaveLength(2);
  expect(report.missing_data.some((item) => /traces.*unavailable/i.test(item))).toBe(true);
  expect(report.missing_data.some((item) => /current snapshots/i.test(item))).toBe(true);
  const timeout = report.evidence.find(
    (item) =>
      item.source === "log" &&
      item.service === submitted.service &&
      item.summary.includes(`Payment request timed out (simulated): order=${problem.orderId}`),
  );
  expect(timeout).toBeDefined();
  if (!timeout) throw new Error("Missing timeout for the order created by this check");
  expect(report.findings.length).toBeGreaterThan(0);
  const view = page.getByRole("region", { name: "Investigation report" });
  await expect(view.getByText("AI analysis completed", { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("overview.png"), fullPage: true });
  await page.screenshot({ path: testInfo.outputPath("poster.png") });
  for (const source of ["Logs", "Metrics", "Actuator"]) {
    await page
      .getByRole("region", { name: "Evidence flow" })
      .getByRole("button", { name: new RegExp(`^${source}:`) })
      .hover();
    await pause(4_000);
  }
  await view.scrollIntoViewIfNeeded();
  await pause(8_000);
  await view.getByRole("button", { name: /^Evidence \(/ }).click();
  await view.getByRole("button").filter({ hasText: timeout.summary }).click();
  const details = view.getByRole("complementary", { name: "Evidence details" });
  await expect(details.getByText(timeout.reference, { exact: true })).toBeVisible();
  await pause(8_000);
  await view.getByRole("button", { name: "Analysis & checks", exact: true }).click();
  await view.getByRole("heading", { name: "Findings", exact: true }).scrollIntoViewIfNeeded();
  await pause(14_000);

  const ids = new Set(report.evidence.map((item) => item.id));
  const cited = [
    ...report.findings.flatMap((item) => item.evidence_ids),
    ...report.hypotheses.flatMap((item) => [
      ...item.supporting_evidence_ids,
      ...item.contradicting_evidence_ids,
    ]),
  ];
  for (const id of new Set(cited)) {
    expect(ids.has(id)).toBe(true);
    await view.getByRole("button", { name: id, exact: true }).first().click();
    await expect(details.getByRole("heading", { name: id, exact: true })).toBeVisible();
    const item = report.evidence.find((candidate) => candidate.id === id);
    if (!item) throw new Error("Unknown model citation");
    await expect(details.getByText(item.reference, { exact: true })).toBeVisible();
  }
  await view
    .getByRole("heading", { name: "Recommended checks", exact: true })
    .scrollIntoViewIfNeeded();
  await pause(14_000);
  await view.getByRole("button", { name: /^Data gaps/ }).click();
  await pause(10_000);
  await page.screenshot({ path: testInfo.outputPath("data-gaps.png"), fullPage: true });

  const downloaded = page.waitForEvent("download");
  await view.getByRole("button", { name: "Export JSON", exact: true }).click();
  const download = await downloaded;
  const exportPath = testInfo.outputPath("investigation-report.json");
  await download.saveAs(exportPath);
  expect(JSON.parse(await readFile(exportPath, "utf8"))).toEqual({
    schema_version: 1,
    request: submitted,
    report,
  });
  await view.getByRole("button", { name: "Analysis & checks", exact: true }).click();
  await view.getByRole("heading", { name: "Findings", exact: true }).scrollIntoViewIfNeeded();
  await pause(8_000);
  expect(submissions).toBe(1);
  expect(browserErrors).toEqual([]);
});
