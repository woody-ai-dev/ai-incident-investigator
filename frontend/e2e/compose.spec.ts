import { expect, test } from "@playwright/test";
import { z } from "zod";
import { reportSchema, requestSchema } from "../src/api/contracts";

test("Compose timeout evidence reaches the browser through the frontend proxy", async ({
  page,
  request,
}) => {
  const ordersUrl = new URL(
    "/api/v1/orders",
    process.env.E2E_ORDERS_URL ?? "http://127.0.0.1:8081",
  );
  const orderResponse = await request.post(ordersUrl.href, {
    data: { productId: "book-1", quantity: 2 },
    timeout: 10_000,
  });
  expect(orderResponse.status()).toBe(504);
  const { orderId } = z
    .object({ code: z.literal("PAYMENT_TIMEOUT"), orderId: z.uuid() })
    .parse(await orderResponse.json());

  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  const document = await page.goto("/");
  expect(document?.status()).toBe(200);
  expect(document?.headers()["content-security-policy"]).toContain("connect-src 'self'");
  await expect(page.getByRole("heading", { name: "Understand what happened." })).toBeVisible();
  await page.getByLabel("What happened?").fill(`Order ${orderId} failed with PAYMENT_TIMEOUT.`);
  await page.getByRole("button", { name: "Last 15 minutes", exact: true }).click();

  // Observe the real browser fetch: no route mocking or direct investigator request.
  const reportResponse = page.waitForResponse(
    (response) =>
      response.url() === new URL("/api/investigations", page.url()).href &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Investigate", exact: true }).click();
  const response = await reportResponse;
  expect(response.status()).toBe(200);
  const submitted = requestSchema.parse(response.request().postDataJSON());
  expect(submitted).toMatchObject({
    service: "order-service",
    environment: "local",
  });
  expect(submitted.description).toContain(orderId);
  expect(Date.parse(submitted.end_time) - Date.parse(submitted.start_time)).toBe(15 * 60_000);

  const payload: unknown = await response.json();
  expect(payload).toHaveProperty("analysis_status", "not_requested");
  const report = reportSchema.parse(payload);
  const timeout = report.evidence.find(
    (item) =>
      item.source === "log" &&
      item.service === "order-service" &&
      item.summary.startsWith("[ERROR]") &&
      item.summary.includes(`Payment request timed out (simulated): order=${orderId}`) &&
      /^local-jsonl:line:\d+$/.test(item.reference),
  );
  expect(timeout, "The report must contain the order created by this test").toBeDefined();
  if (!timeout) throw new Error("Created-order timeout evidence is missing");

  const reportView = page.getByRole("region", { name: "Investigation report" });
  await expect(reportView.getByText("AI analysis disabled", { exact: true })).toBeVisible();
  const flow = page.getByRole("region", { name: "Evidence flow" });
  for (const source of ["Logs", "Metrics", "Actuator"]) {
    await expect(
      flow.getByRole("button", {
        name: new RegExp(`^${source}: .+ Show source details\\.$`),
      }),
    ).toBeVisible();
  }

  const timeoutRow = reportView.getByRole("button").filter({ hasText: timeout.summary });
  await expect(timeoutRow).toHaveCount(1);
  await expect(timeoutRow.getByText("log", { exact: true })).toBeVisible();
  await timeoutRow.click();
  const details = reportView.getByRole("complementary", {
    name: "Evidence details",
  });
  await expect(details.getByRole("heading", { name: timeout.id, exact: true })).toBeVisible();
  await expect(details.getByText(timeout.summary, { exact: true })).toBeVisible();
  await expect(details.getByText(timeout.reference, { exact: true })).toBeVisible();
  await expect(details.getByText("log", { exact: true })).toBeVisible();
  expect(browserErrors).toEqual([]);
});

test("floating menus work under the production Content Security Policy", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  const document = await page.goto("/");
  const policy = document?.headers()["content-security-policy"] ?? "";
  expect(policy).toContain("script-src 'self'");
  expect(policy).not.toContain("'unsafe-inline'");
  expect(document?.headers()["cache-control"]).toContain("no-store");
  const nonce = await page.locator('meta[name="style-nonce"]').getAttribute("content");
  expect(nonce).toMatch(/^[a-f0-9]{32}$/);
  expect(policy).toContain(`style-src 'self' 'nonce-${nonce}'`);

  for (const label of ["Service", "Environment", "Service"]) {
    await page.getByRole("combobox", { name: label, exact: true }).click();
    await expect(page.getByRole("listbox")).toBeVisible();
    await expect(page.locator("body")).toHaveCSS("overflow", "hidden");
    const styleNonces = await page
      .locator("style")
      .evaluateAll((styles) => styles.map((style) => (style as HTMLStyleElement).nonce));
    expect(styleNonces.length).toBeGreaterThanOrEqual(2);
    expect(styleNonces.every((value) => value === nonce)).toBe(true);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("listbox")).toBeHidden();
    await expect(page.locator("body")).not.toHaveAttribute("data-scroll-locked");
  }
  await page.reload();
  expect(await page.locator('meta[name="style-nonce"]').getAttribute("content")).not.toBe(nonce);
  expect(errors).toEqual([]);
});
