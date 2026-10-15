import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "ui.spec.ts",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 2,
  timeout: 30_000,
  globalTimeout: 240_000,
  expect: { timeout: 5_000 },
  outputDir: "test-results/ui",
  reporter: [["list"], ["html", { outputFolder: "playwright-report/ui", open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    browserName: "chromium",
    viewport: { width: 1400, height: 1000 },
    locale: "en-GB",
    timezoneId: "UTC",
    reducedMotion: "reduce",
    serviceWorkers: "block",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npm run e2e:serve",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false,
    timeout: 60_000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
  },
});
