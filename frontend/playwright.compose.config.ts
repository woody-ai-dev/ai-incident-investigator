import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig({
  ...base,
  testMatch: "compose.spec.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  outputDir: "test-results/compose",
  reporter: [["list"], ["html", { outputFolder: "playwright-report/compose", open: "never" }]],
  use: {
    ...base.use,
    baseURL: process.env.E2E_COMPOSE_URL ?? "http://127.0.0.1:3000",
  },
  webServer: [],
});
