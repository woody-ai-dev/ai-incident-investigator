import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

if (process.env.ALLOW_LIVE_LLM !== "true") {
  throw new Error("Set ALLOW_LIVE_LLM=true to allow the billable live-model browser check.");
}

export default defineConfig({
  ...base,
  testMatch: "live.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 240_000,
  outputDir: "test-results/live",
  reporter: [["list"], ["html", { outputFolder: "playwright-report/live", open: "never" }]],
  use: {
    ...base.use,
    baseURL: process.env.E2E_COMPOSE_URL ?? "http://127.0.0.1:3000",
    reducedMotion: "no-preference",
    video: { mode: "on", size: { width: 1400, height: 1000 } },
    screenshot: "on",
  },
  webServer: [],
});
