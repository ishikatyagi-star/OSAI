import { expect, test } from "@playwright/test";
import { mockEmptyNotificationInbox, mockExternalFonts } from "./helpers";

test("Automations follow scheduler capability and surface destination outages", async ({ page }) => {
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
        email: "qa@example.com",
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
  await page.route("**/api/capabilities", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        environment: "test",
        scheduler: true,
        automation_cadences: ["manual", "hourly", "daily", "weekly"],
        connectors: true,
        sql_sources: true,
        workflow_execution: true,
        semantic_embeddings: true,
        embedding_model: "qa-embedding",
        google_oauth: false,
        email_login: true,
        zoom_webhook: false,
      }),
    })
  );
  await page.route("**/api/automations", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/workflows", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
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
        as_of: "2026-07-21T10:00:00Z",
      }),
    })
  );
  await page.route("**/api/integrations", (route) =>
    route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"offline"}' })
  );

  await page.goto("/automations");
  await expect(page.getByRole("heading", { name: "Automations" })).toBeVisible();
  const cadence = page.getByRole("combobox", { name: "Automation cadence" });
  await cadence.click();
  const hourly = page.getByRole("option", { name: "Hourly", exact: true });
  await expect(hourly).toBeEnabled();
  await hourly.click();
  await expect(page.getByText(/run automatically on the hourly cadence/i)).toBeVisible();
  await expect(page.getByText(/recurring cadences are enabled/i)).toBeVisible();

  await page.getByRole("tab", { name: "From transcript" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Connected destinations could not be loaded" })
  ).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Action item destination" })).toContainText(
    "Manual Review"
  );
});
