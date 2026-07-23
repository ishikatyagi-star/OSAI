import { expect, test, type Page } from "@playwright/test";
import { mockEmptyNotificationInbox, mockExternalFonts } from "./helpers";

const OPTIMIZED_LOGO =
  "/_next/image?url=%2Fbrand%2Fsheldon-ai-logo.png&w=64&q=75";

function watchImageOptimizerFailures(page: Page) {
  const failures: string[] = [];

  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.pathname === "/_next/image" && response.status() >= 400) {
      failures.push(`${response.status()} ${url.pathname}${url.search}`);
    }
  });

  return () => expect(failures, failures.join("\n")).toEqual([]);
}

async function expectRenderedImagesLoaded(page: Page) {
  await page.waitForLoadState("networkidle");
  const images = page.locator('img[src*="/_next/image"]');
  await expect(images.first()).toBeVisible();
  const broken = await images.evaluateAll((elements) =>
    elements
      .filter((element) => {
        const image = element as HTMLImageElement;
        return !image.complete || image.naturalWidth === 0;
      })
      .map((element) => (element as HTMLImageElement).currentSrc)
  );
  expect(broken).toEqual([]);
}

async function seedAuthenticatedDashboard(page: Page) {
  await mockExternalFonts(page);
  await mockEmptyNotificationInbox(page);
  await page.addInitScript(() => {
    localStorage.setItem("osai_authed", "1");
    localStorage.setItem("osai_org_id", "qa-org");
    localStorage.setItem("osai_org_name", "QA Workspace");
    localStorage.setItem("osai_user_name", "QA User");
  });
  await page.route("**/api/auth/session", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user_id: "qa-user",
        email: "qa@example.com",
        display_name: "QA User",
        org_id: "qa-org",
        org_name: "QA Workspace",
        role: "member",
        is_admin: false,
        data_tier: "normal",
        permissions: [],
        department_id: null,
      }),
    })
  );
  await page.route("**/api/dashboard/metrics", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total_documents: 0,
        documents_by_connector: {},
        documents_by_tier: {},
        connectors_connected: 0,
        connector_statuses: [],
        pending_decisions: 0,
        pending_actions: 0,
        recent_decisions: [],
        sync_runs_total: 0,
        sync_runs_succeeded: 0,
        last_sync_at: null,
        members: 1,
        departments: 0,
        automations: 0,
        as_of: "2026-07-22T00:00:00Z",
      }),
    })
  );
}

test.describe("production image optimization", () => {
  test("serves a non-empty optimized image", async ({ request }) => {
    const response = await request.get(OPTIMIZED_LOGO, {
      headers: { Accept: "image/webp" },
    });

    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toMatch(/^image\//);
    expect((await response.body()).byteLength).toBeGreaterThan(0);
  });

  test("login renders without failed optimizer responses", async ({ page }) => {
    await mockExternalFonts(page);
    await page.route("**/api/auth/config", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ google_enabled: true, email_login_enabled: false }),
      })
    );
    const expectNoFailures = watchImageOptimizerFailures(page);

    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Welcome to Sheldon" })).toBeVisible();
    await expectRenderedImagesLoaded(page);
    expectNoFailures();
  });

  test("demo renders without failed optimizer responses", async ({ page }) => {
    await mockExternalFonts(page);
    await page.route("**/api/auth/logout", (route) => route.fulfill({ status: 204 }));
    const expectNoFailures = watchImageOptimizerFailures(page);

    await page.goto("/demo");
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await expectRenderedImagesLoaded(page);
    expectNoFailures();
  });

  test("authenticated sidebar renders without failed optimizer responses", async ({ page }) => {
    await seedAuthenticatedDashboard(page);
    const expectNoFailures = watchImageOptimizerFailures(page);

    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
    await expectRenderedImagesLoaded(page);
    expectNoFailures();
  });
});
