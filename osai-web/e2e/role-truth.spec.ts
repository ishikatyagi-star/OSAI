import { expect, test, type Page } from "@playwright/test";
import { mockEmptyNotificationInbox, mockExternalFonts } from "./helpers";

const AS_OF = "2026-07-21T10:00:00Z";

async function seedSignedInWorkspace(page: Page) {
  await mockExternalFonts(page);
  await mockEmptyNotificationInbox(page);
  await page.addInitScript(() => {
    localStorage.setItem("osai_authed", "1");
    localStorage.setItem("osai_org_id", "qa-org");
    localStorage.setItem("osai_org_name", "QA Workspace");
    localStorage.setItem("osai_user_name", "QA User");
  });
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
        members: 2,
        departments: 0,
        automations: 0,
        as_of: AS_OF,
      }),
    })
  );
}

function session(isAdmin: boolean) {
  return {
    user_id: "qa-user",
    email: "qa@example.com",
    display_name: "QA User",
    org_id: "qa-org",
    org_name: "QA Workspace",
    role: isAdmin ? "admin" : "member",
    is_admin: isAdmin,
    data_tier: isAdmin ? "red" : "normal",
    permissions: [],
    department_id: null,
  };
}

test("Data hides admin controls and skips source loading for members", async ({ page }) => {
  await seedSignedInWorkspace(page);
  await page.route("**/api/auth/session", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session(false)) })
  );
  let sourceLoads = 0;
  await page.route("**/api/sql/sources", (route) => {
    sourceLoads += 1;
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.goto("/sql");
  await expect(page.getByText("Only workspace admins can connect and query live databases.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add source" })).toHaveCount(0);
  expect(sourceLoads).toBe(0);
});

test("Data preserves source management for admins", async ({ page }) => {
  await seedSignedInWorkspace(page);
  await page.route("**/api/auth/session", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session(true)) })
  );
  let sourceLoads = 0;
  await page.route("**/api/sql/sources", (route) => {
    sourceLoads += 1;
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.goto("/sql");
  await expect(page.getByRole("button", { name: "Add source" })).toBeEnabled();
  await expect(page.getByText(/No data sources yet/)).toBeVisible();
  expect(sourceLoads).toBeGreaterThan(0);
});

test("Dashboard renders the metrics timestamp returned by the API", async ({ page }) => {
  await seedSignedInWorkspace(page);
  await page.goto("/dashboard");
  await expect(page.locator(`time[datetime="${AS_OF}"]`)).toBeVisible();
  await expect(page.getByText("Metrics as of", { exact: false })).toBeVisible();
});

test("self-demotion removes stale Team admin controls", async ({ page }) => {
  await seedSignedInWorkspace(page);
  let isAdmin = true;
  let sessionChecks = 0;
  await page.route("**/api/auth/session", (route) => {
    sessionChecks += 1;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session(isAdmin)) });
  });
  await page.route("**/api/team/members", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        { ...session(isAdmin), id: "qa-user", role: isAdmin ? "admin" : "member", department: null, status: "active" },
        { ...session(true), id: "other-admin", email: "other@example.com", display_name: "Other Admin", department: null, status: "active" },
      ]),
    })
  );
  await page.route("**/api/team/departments", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/team/invites", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/team/members/qa-user", async (route) => {
    expect(route.request().method()).toBe("PATCH");
    expect(await route.request().postDataJSON()).toMatchObject({ role: "member" });
    isAdmin = false;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: "qa-user", role: "member", department_id: null }),
    });
  });

  await page.goto("/team");
  const role = page.getByRole("combobox", { name: "Role for QA User" });
  await role.click();
  await page.getByRole("option", { name: "member", exact: true }).click();

  await expect(role).toBeDisabled();
  await expect(page.getByRole("button", { name: /Remove/ })).toHaveCount(0);
  await page.getByRole("tab", { name: /Invites/ }).click();
  await expect(page.getByText("Only workspace admins can create or view invitations.")).toBeVisible();
  expect(sessionChecks).toBeGreaterThanOrEqual(2);
});

test("Evals refreshes a stale admin session after a forbidden run", async ({ page }) => {
  await seedSignedInWorkspace(page);
  let isAdmin = true;
  let sessionChecks = 0;
  let evalRuns = 0;
  await page.route("**/api/auth/session", (route) => {
    sessionChecks += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(session(isAdmin)),
    });
  });
  await page.route("**/api/evals", (route) => {
    evalRuns += 1;
    isAdmin = false;
    return route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Admin access required" }),
    });
  });

  await page.goto("/evals");
  await page.getByRole("button", { name: "Run eval suite" }).click();

  await expect(page.getByText("Admin access required", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);
  expect(evalRuns).toBe(1);
  expect(sessionChecks).toBeGreaterThanOrEqual(2);
});

test("Graph shows an outage and retries instead of masquerading it as empty", async ({ page }) => {
  await seedSignedInWorkspace(page);
  await page.route("**/api/auth/session", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session(true)) })
  );
  let attempts = 0;
  await page.route("**/api/graph/access", (route) => {
    attempts += 1;
    if (attempts === 1) {
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "The access map is temporarily unavailable." }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        users: [{ id: "qa-user", label: "QA User", role: "admin", department: "QA" }],
        connectors: [{ key: "notion", label: "Notion", connected: true }],
        access: [{ user_id: "qa-user", connector_key: "notion", tier: "red", doc_count: 3 }],
      }),
    });
  });

  await page.goto("/graph");
  await expect(page.locator(".async-state[role='alert']")).toContainText(
    "The access map could not be loaded."
  );
  await expect(page.getByText("No access map yet")).toHaveCount(0);
  await page.getByRole("button", { name: "Retry" }).click();

  await expect(page.getByRole("rowheader", { name: /QA User/ })).toBeVisible();
  expect(attempts).toBe(2);
});
