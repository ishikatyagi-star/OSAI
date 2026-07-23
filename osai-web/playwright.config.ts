import { defineConfig } from "@playwright/test";

// Golden-path smoke suite. Runs the app in demo mode (no backend needed) so it
// can execute anywhere: locally, in CI, pre-deploy. The point is catching the
// class of regression that blanks a page or breaks the core flow. The broader
// QA suite lives in ./e2e and shares this configuration.
const port = Number(process.env.PLAYWRIGHT_PORT ?? 3210);
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: ".",
  testMatch: ["e2e/**/*.spec.ts", "tests/e2e/**/*.spec.ts"],
  outputDir: "output/playwright/test-results",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  timeout: 60_000,
  expect: { timeout: 8_000 },
  reporter: [
    ["list"],
    ["html", { outputFolder: "output/playwright/report", open: "never" }],
  ],
  use: {
    baseURL,
    browserName: "chromium",
    colorScheme: "light",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
    viewport: { width: 1280, height: 900 },
  },
  webServer:
    process.env.PLAYWRIGHT_SKIP_WEBSERVER === "1"
      ? undefined
      : {
          command:
            process.env.PLAYWRIGHT_WEB_SERVER_COMMAND ??
            `npm run dev -- --hostname 127.0.0.1 --port ${port}`,
          url: baseURL,
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
          stdout: "pipe",
          stderr: "pipe",
        },
});
