import { expect, test } from "@playwright/test";
import {
  mockEmptyNotificationInbox,
  mockExternalFonts,
  watchRuntimeIssues,
} from "./helpers";

test("connected native Freshdesk can sync without claiming OAuth disconnect support", async ({
  page,
}) => {
  await mockExternalFonts(page);
  await mockEmptyNotificationInbox(page);
  await page.addInitScript(() => {
    localStorage.setItem("osai_authed", "1");
    localStorage.setItem("osai_org_id", "qa-org");
    localStorage.setItem("osai_org_name", "QA Workspace");
    localStorage.setItem("osai_user_name", "QA Admin");
  });

  await page.route("**/api/auth/session", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user_id: "qa-admin",
        email: "qa@example.test",
        display_name: "QA Admin",
        org_id: "qa-org",
        org_name: "QA Workspace",
        role: "admin",
        is_admin: true,
        data_tier: "red",
        permissions: [],
        department_id: null,
      }),
    })
  );

  const freshdesk = {
    key: "freshdesk",
    display_name: "Freshdesk",
    capabilities: ["sync", "search", "execute"],
    auth_state: "connected",
    scopes: ["tickets:read"],
    last_sync: "2026-07-22T10:00:00Z",
    sync_error: null,
    source: "native",
  };
  await page.route("**/api/integrations", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([freshdesk]),
    })
  );
  await page.route("**/api/dashboard/metrics", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total_documents: 47,
        documents_by_connector: { freshdesk: 47 },
        documents_by_tier: { normal: 47 },
        connectors_connected: 1,
        connector_statuses: [],
        pending_decisions: 0,
        pending_actions: 0,
        recent_decisions: [],
        sync_runs_total: 1,
        sync_runs_succeeded: 1,
        last_sync_at: "2026-07-22T10:00:00Z",
        members: 1,
        departments: 0,
        automations: 0,
        as_of: "2026-07-22T10:00:00Z",
      }),
    })
  );
  await page.route("**/api/sync-runs", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/integrations/freshdesk/healthcheck", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ healthy: true, message: "Freshdesk credentials configured" }),
    })
  );
  await page.route("**/api/integrations/freshdesk/documents?**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );

  let syncCalls = 0;
  await page.route("**/api/integrations/freshdesk/sync", (route) => {
    syncCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "succeeded", documents_indexed: 3 }),
    });
  });

  const runtime = watchRuntimeIssues(page);
  await page.goto("/integrations");
  await expect(page.getByRole("heading", { name: "Integrations" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Freshdesk" })).toBeVisible();
  await expect(page.getByText(/legacy connection is (?:not supported|unavailable)/i)).toHaveCount(0);
  await expect(
    page.getByText("Connection settings for this source are managed by your deployment administrator.")
  ).toBeVisible();

  await page.getByRole("button", { name: "Sync now" }).click();
  await expect(page.getByText("Indexed 3 files")).toBeVisible();
  expect(syncCalls).toBe(1);

  await page.getByRole("button", { name: "Manage" }).click();
  const dialog = page.getByRole("dialog", { name: "Freshdesk" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Freshdesk credentials configured")).toBeVisible();
  await expect(
    dialog.getByText("Connection settings are managed by your deployment administrator.")
  ).toBeVisible();
  await expect(dialog.getByRole("button", { name: /Disconnect Freshdesk/i })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Sync now" })).toBeVisible();
  runtime.expectClean();
});
