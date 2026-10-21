import { expect, test } from "@playwright/test";
import { storedInvestigationSchema } from "../src/api/history";

test("saves a real report, lists it, reloads its snapshot and filters history", async ({
  page,
  request,
}) => {
  const response = await request.post("/api/investigations", {
    data: {
      service: "order-service",
      environment: "local",
      start_time: new Date(Date.now() - 300_000).toISOString(),
      end_time: new Date().toISOString(),
      description: "Read-only persisted history browser check.",
    },
  });
  expect(response.ok()).toBe(true);
  const id = response.headers()["x-investigation-id"];
  expect(id).toBeTruthy();
  if (!id) throw new Error("The persistence demo must return X-Investigation-ID.");
  const snapshot = await request.get(`/api/investigations/${id}`);
  const saved = storedInvestigationSchema.parse(await snapshot.json());
  expect(saved.report.analysis_status).toBe("not_requested");
  let posts = 0;
  page.on("request", (req) => {
    if (req.method() === "POST") posts++;
  });
  await page.goto("/investigations?service=order-service&environment=local");
  await page.getByRole("link", { name: `Open investigation ${id}` }).click();
  await expect(page.getByRole("region", { name: "Saved metadata" })).toContainText(id);
  await expect(page.getByRole("region", { name: "Investigation report" })).toContainText(
    saved.report.summary,
  );
  await page.reload();
  await expect(page.getByRole("region", { name: "Investigation report" })).toContainText(
    saved.report.summary,
  );
  await page.getByRole("link", { name: "← Back to investigations" }).click();
  await expect(page.getByRole("combobox", { name: "Service", exact: true })).toHaveText(
    "order-service",
  );
  await page.getByRole("combobox", { name: "Service", exact: true }).click();
  await page.getByRole("option", { name: "All services", exact: true }).click();
  await page.getByLabel("Created until (excluded)", { exact: true }).fill("2000-01-01T00:00");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByRole("heading", { name: "No saved investigations" })).toBeVisible();
  expect(posts).toBe(0);
  const after = await request.get(`/api/investigations/${id}`);
  expect(await after.json()).toEqual(saved);
});
