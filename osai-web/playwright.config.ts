import { defineConfig } from "@playwright/test";

// Golden-path smoke suite. Runs the app in demo mode (no backend needed) so it
// can execute anywhere: locally, in CI, pre-deploy. The point is catching the
// class of regression that blanks a page or breaks the core flow, not deep
// feature coverage.
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: "http://localhost:3210",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npm run dev -- --port 3210",
    url: "http://localhost:3210/login",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
