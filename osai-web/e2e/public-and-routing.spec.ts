import { expect, test } from "@playwright/test";
import {
  mockExternalFonts,
  openDemoRoute,
  seedDemoWorkspace,
  watchRuntimeIssues,
} from "./helpers";

test.describe("public entry and authentication boundary", () => {
  test("build identity is available and explicitly non-cacheable", async ({ request }) => {
    const response = await request.get("/build-info");

    expect(response.status()).toBe(200);
    expect(response.headers()["cache-control"]).toContain("no-store");
    await expect(response.json()).resolves.toMatchObject({
      status: "ok",
      service: "osai-web",
    });
  });

  test("landing page exposes the primary paths and security headers", async ({ page }) => {
    await mockExternalFonts(page);
    const runtime = watchRuntimeIssues(page);
    const response = await page.goto("/");

    expect(response?.status()).toBe(200);
    await expect(
      page.getByRole("heading", { name: "Run your company on autopilot." })
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Sign in" }).first()).toHaveAttribute(
      "href",
      "/login"
    );
    await expect(page.getByRole("link", { name: "Try a Demo" }).first()).toHaveAttribute(
      "href",
      "/demo"
    );
    await expect(
      page.getByRole("link", { name: "Book a Call (opens in a new tab)" }).first()
    ).toHaveAttribute("rel", /noopener/);

    const headers = response?.headers() ?? {};
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
    runtime.expectClean();
  });

  test("login stays usable while auth configuration is checked", async ({ page }) => {
    await mockExternalFonts(page);
    await page.route("**/api/auth/config", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ google_enabled: true, email_login_enabled: false }),
      })
    );
    const runtime = watchRuntimeIssues(page);
    await page.goto("/login#invite=opaque_token-1234567890");

    await expect(page.getByRole("heading", { name: "Welcome to Sheldon" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Continue with Google" })).toBeEnabled();
    await expect(page.getByText(/You've been invited/)).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("button", { name: /Try Demo/ })).toBeEnabled();
    runtime.expectClean();
  });

  test("login and callback error links return to the rendered site", async ({ page }) => {
    await mockExternalFonts(page);
    await page.route("**/api/auth/config", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ google_enabled: true, email_login_enabled: false }),
      })
    );
    const runtime = watchRuntimeIssues(page);

    await page.goto("/login");
    await page.getByRole("link", { name: /Back to site/ }).click();
    await expect(
      page.getByRole("heading", { name: "Run your company on autopilot." })
    ).toBeVisible();

    await page.goto("/auth/callback");
    await expect(page.getByRole("heading", { name: /We couldn.t sign you in/i })).toBeVisible();
    await page.getByRole("link", { name: "Back to site" }).click();
    await expect(
      page.getByRole("heading", { name: "Run your company on autopilot." })
    ).toBeVisible();
    runtime.expectClean();
  });

  test("a failed callback scrubs its bearer fragment and cancels its redirect on recovery", async ({ page }) => {
    await mockExternalFonts(page);
    await page.route("**/api/auth/session", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 200));
      await route.fulfill({ status: 503, body: "unavailable" });
    });

    await page.goto("/auth/callback#token=qa-secret&org_id=qa-org");
    await expect(page).not.toHaveURL(/qa-secret|#token=/);
    await expect(page.getByRole("heading", { name: /We couldn.t sign you in/i })).toBeVisible();

    await page.getByRole("link", { name: "Back to site" }).click();
    await expect(page.getByRole("heading", { name: "Run your company on autopilot." })).toBeVisible();
    await page.waitForTimeout(2200);
    await expect(page).toHaveURL(/\/$/);
  });

  test("signed-out users are redirected away from protected routes", async ({ page }) => {
    await mockExternalFonts(page);
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "Welcome to Sheldon" })).toBeVisible();
  });

  test("the public demo entry creates only non-sensitive local state", async ({ page }) => {
    await mockExternalFonts(page);
    await page.goto("/demo");
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await expect(page.getByText("Demo workspace", { exact: false }).first()).toBeVisible();

    const state = await page.evaluate(() => ({
      authed: localStorage.getItem("osai_authed"),
      orgId: localStorage.getItem("osai_org_id"),
      legacyToken: localStorage.getItem("osai_token"),
    }));
    expect(state).toEqual({ authed: "1", orgId: "demo-org", legacyToken: null });
  });
});

const canonicalRoutes = [
  ["/dashboard", "Dashboard"],
  ["/ask", "Ask Sheldon"],
  ["/analytics", "Analytics"],
  ["/decisions", "Decision Log"],
  ["/artifacts", "Artifacts"],
  ["/graph", "Org Graph · Access Map"],
  ["/team", "Team"],
  ["/automations", "Automations"],
  ["/integrations", "Integrations"],
  ["/sync-runs", "Sync Runs"],
  ["/settings", "Settings"],
  ["/sql", "Data"],
  ["/evals", "Evals"],
] as const;

test.describe("canonical demo routes", () => {
  for (const [path, heading] of canonicalRoutes) {
    test(`${path} renders its real page without runtime failures`, async ({ page }) => {
      const runtime = watchRuntimeIssues(page);
      await openDemoRoute(page, path);
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
      await expect(page.getByText("DEMO", { exact: true })).toBeVisible();
      runtime.expectClean();
    });
  }

  test("an unknown workflow has a real not-found state", async ({ page }) => {
    const runtime = watchRuntimeIssues(page);
    await openDemoRoute(page, "/workflows/not-a-real-run");
    await expect(page.getByText("Workflow run not found.")).toBeVisible();
    await expect(page.getByText(/check your connection/i)).toHaveCount(0);
    runtime.expectClean();
  });
});

const redirects = [
  ["/context-inbox", /\/ask$/],
  ["/inbox", /\/ask$/],
  ["/decision-log", /\/decisions$/],
  ["/team-board", /\/decisions\?source=osai$/],
  ["/org-graph", /\/graph$/],
  ["/data-routing", /\/integrations\?tab=routing$/],
  ["/settings/data-routing", /\/integrations\?tab=routing$/],
  ["/workflows", /\/automations$/],
  ["/search", /\/ask\?mode=search$/],
  ["/dashboards", /\/analytics$/],
  ["/settings/advanced", /\/evals$/],
] as const;

test.describe("legacy and folded routes", () => {
  for (const [from, destination] of redirects) {
    test(`${from} resolves to its canonical surface`, async ({ page }) => {
      await seedDemoWorkspace(page);
      await page.goto(from);
      await expect(page).toHaveURL(destination);
    });
  }
});
