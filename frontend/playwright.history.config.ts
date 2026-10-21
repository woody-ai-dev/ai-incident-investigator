import { defineConfig } from "@playwright/test";
import compose from "./playwright.compose.config";

export default defineConfig({
  ...compose,
  testMatch: "history.compose.spec.ts",
  outputDir: "test-results/history",
  reporter: [["list"], ["html", { outputFolder: "playwright-report/history", open: "never" }]],
});
