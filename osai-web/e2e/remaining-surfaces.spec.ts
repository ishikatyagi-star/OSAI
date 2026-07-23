import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import {
  mockEmptyNotificationInbox,
  mockExternalFonts,
  openDemoRoute,
  seedDemoWorkspace,
  watchRuntimeIssues,
} from "./helpers";

test("onboarding reports a failed create and succeeds on retry", async ({ page }) => {
  await mockExternalFonts(page);
  await page.addInitScript(() => {
    localStorage.setItem("osai_authed", "1");
    localStorage.removeItem("osai_org_id");
  });
  let attempts = 0;
  await page.route("**/api/auth/config", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ google_enabled: false, email_login_enabled: true }),
    })
  );
  await page.route("**/api/orgs", (route) => {
    attempts += 1;
    if (attempts === 1) return route.fulfill({ status: 503, body: "unavailable" });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        org_id: "qa-org",
        name: "QA Workspace",
        admin_email: "admin@example.com",
        admin_display_name: "QA Admin",
      }),
    });
  });
  await page.route("**/api/auth/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user_id: "qa-admin",
        org_id: "qa-org",
        role: "admin",
        token: "returned-once-not-persisted",
      }),
    })
  );

  await page.goto("/onboarding");
  await page.getByLabel("Organization name").fill("QA Workspace");
  await page.getByLabel("Your name").fill("QA Admin");
  await page.getByLabel("Your work email").fill("admin@example.com");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Could not create your workspace. Please try again." })
  ).toHaveText("Could not create your workspace. Please try again.");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Your workspace is ready" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Connect your tools/ })).toBeVisible();
  expect(attempts).toBe(2);
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("osai_token")))
    .toBeNull();
});

test("production onboarding cannot create a workspace without verified sign-in", async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.removeItem("osai_org_id");
  });
  let provisionAttempts = 0;
  await page.route("**/api/auth/config", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ google_enabled: true, email_login_enabled: false }),
    })
  );
  await page.route("**/api/orgs", (route) => {
    provisionAttempts += 1;
    return route.abort();
  });

  await page.goto("/onboarding");

  await expect(page).toHaveURL(/\/login$/);
  expect(provisionAttempts).toBe(0);
});

test("graph filters and analytics refresh exercise their rendered controls", async ({ page }) => {
  const runtime = watchRuntimeIssues(page);
  await openDemoRoute(page, "/graph");
  await page.getByLabel("Filter org graph by department").click();
  await page.getByRole("option", { name: "Engineering" }).click();
  await expect(page.getByText("2 people", { exact: true })).toBeVisible();
  await page.getByLabel("Filter org graph by role").click();
  await page.getByRole("option", { name: "engineer" }).click();
  await expect(page.getByText("1 people", { exact: true })).toBeVisible();

  await page.goto("/analytics");
  await expect(page.getByText("Documents indexed", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByText("Documents indexed", { exact: true })).toBeVisible();
  runtime.expectClean();
});

test("workflow actions require confirmation and remain harmless in demo", async ({ page }) => {
  const runtime = watchRuntimeIssues(page);
  await openDemoRoute(page, "/workflows/workflow-q3-planning");
  const approve = page.getByRole("button", {
    name: /Approve and execute: Finalise Q3 product roadmap/,
  });
  await approve.click();
  const dialog = page.getByRole("dialog", { name: "Approve and execute this action?" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(approve).toBeFocused();

  await approve.click();
  await dialog.getByRole("button", { name: "Approve action" }).click();
  await expect(page.getByText("Approved in the demo; no external tool was changed.")).toBeVisible();
  await expect(approve).toHaveCount(0);
  runtime.expectClean();
});

for (const path of [
  "/analytics",
  "/artifacts",
  "/graph",
  "/automations",
  "/sync-runs",
  "/sql",
  "/notifications",
  "/workflows/workflow-q3-planning",
]) {
  test(`${path} has no serious WCAG 2.2 A/AA axe findings`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await seedDemoWorkspace(page);
    await mockEmptyNotificationInbox(page);
    await page.goto(path);
    await expect(page.locator("h1")).toBeVisible();
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(
      results.violations.filter((violation) =>
        ["serious", "critical"].includes(violation.impact ?? "")
      )
    ).toEqual([]);
  });
}
