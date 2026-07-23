import { expect, test, type Page, type Route } from "@playwright/test";
import type { Integration } from "../lib/types";
import { mockEmptyNotificationInbox, mockExternalFonts } from "./helpers";

const session = {
  user_id: "qa-admin",
  email: "admin@example.com",
  display_name: "QA Admin",
  org_id: "qa-org",
  org_name: "QA Workspace",
  role: "admin",
  is_admin: true,
  data_tier: "red",
  permissions: [],
  department_id: null,
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

async function seedSignedInWorkspace(page: Page) {
  await mockExternalFonts(page);
  await mockEmptyNotificationInbox(page);
  await page.addInitScript(() => {
    localStorage.setItem("osai_authed", "1");
    localStorage.setItem("osai_org_id", "qa-org");
    localStorage.setItem("osai_org_name", "QA Workspace");
    localStorage.setItem("osai_user_id", "qa-admin");
    localStorage.setItem("osai_user_email", "admin@example.com");
    localStorage.setItem("osai_user_name", "QA Admin");
  });
  await page.route("**/api/auth/session", (route) => json(route, session));
}

async function mockIntegrationBootstrap(
  page: Page,
  integrations: () => Integration[]
) {
  await page.route("**/api/integrations", (route) => json(route, integrations()));
  await page.route("**/api/dashboard/metrics", (route) =>
    json(route, {
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
      as_of: "2026-07-22T12:00:00Z",
    })
  );
  await page.route("**/api/sync-runs", (route) => json(route, []));
}

test("the connector catalog searches, paginates, deduplicates, and reports OAuth start failure", async ({
  page,
}) => {
  await seedSignedInWorkspace(page);
  await mockIntegrationBootstrap(page, () => []);

  const catalogRequests: string[] = [];
  await page.route("**/api/integrations/composio/toolkits**", (route) => {
    const url = new URL(route.request().url());
    catalogRequests.push(url.search);
    const search = url.searchParams.get("search");
    const cursor = url.searchParams.get("cursor");
    if (search === "Slack") {
      return json(route, {
        items: [
          { slug: "slack", name: "Slack", no_auth: false, tools_count: 12, categories: ["Chat"] },
        ],
        next_cursor: null,
      });
    }
    if (cursor === "catalog-page-2") {
      return json(route, {
        items: [
          { slug: "gmail", name: "Gmail", no_auth: false, tools_count: 8, categories: ["Email"] },
          { slug: "notion", name: "Notion", no_auth: false, tools_count: 7, categories: ["Knowledge"] },
        ],
        next_cursor: null,
      });
    }
    return json(route, {
      items: [
        { slug: "gmail", name: "Gmail", no_auth: false, tools_count: 8, categories: ["Email"] },
      ],
      next_cursor: "catalog-page-2",
    });
  });

  const connectRequests: Array<{ method: string; body: unknown; org: string | null }> = [];
  await page.route("**/api/integrations/composio/connect/slack", async (route) => {
    connectRequests.push({
      method: route.request().method(),
      body: await route.request().postDataJSON(),
      org: await route.request().headerValue("x-org-id"),
    });
    return json(route, { error: "OAuth is unavailable in the QA environment." });
  });

  await page.goto("/integrations?catalog=1");
  const dialog = page.getByRole("dialog", { name: "Add a connector" });
  await expect(dialog).toBeVisible();
  await expect(page).toHaveURL(/\/integrations$/);
  await expect(dialog.getByText("Gmail", { exact: true })).toBeVisible();

  await dialog.getByRole("button", { name: "Load more" }).click();
  await expect(dialog.getByText("Notion", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Gmail", { exact: true })).toHaveCount(1);

  await dialog.getByLabel("Search connector catalog").fill("Slack");
  await expect(dialog.getByText("Slack", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Gmail", { exact: true })).toHaveCount(0);
  await dialog.getByRole("button", { name: "Connect Slack" }).click();
  await expect(dialog.getByText("OAuth is unavailable in the QA environment.")).toBeVisible();

  expect(catalogRequests).toEqual(["", "?cursor=catalog-page-2", "?search=Slack"]);
  expect(connectRequests).toEqual([{ method: "POST", body: {}, org: "qa-org" }]);
});

test("a Composio connector redirects on connect and stays connected until disconnect succeeds", async ({
  page,
}) => {
  await seedSignedInWorkspace(page);
  let connected = false;
  const integration = (): Integration => ({
    key: "slack",
    display_name: "Slack",
    capabilities: ["sync", "search", "execute"],
    auth_state: connected ? "connected" : "not_configured",
    scopes: connected ? ["channels:history"] : [],
    last_sync: null,
    sync_error: null,
    source: "composio",
    account_email: connected ? "qa-slack@example.com" : null,
  });
  await mockIntegrationBootstrap(page, () => [integration()]);
  await page.route("**/api/integrations/slack/healthcheck", (route) =>
    json(route, { healthy: true, message: "Slack connection healthy" })
  );
  await page.route("**/api/integrations/slack/documents?**", (route) => json(route, []));

  const firstConnect = deferred();
  let connectCalls = 0;
  const mutations: Array<{ path: string; method: string; body: unknown; org: string | null }> = [];
  await page.route("**/api/integrations/composio/connect/slack", async (route) => {
    connectCalls += 1;
    mutations.push({
      path: new URL(route.request().url()).pathname,
      method: route.request().method(),
      body: await route.request().postDataJSON(),
      org: await route.request().headerValue("x-org-id"),
    });
    if (connectCalls === 1) {
      await firstConnect.promise;
      return json(route, { detail: "OAuth start unavailable" }, 503);
    }
    connected = true;
    return json(route, {
      redirect_url: `${new URL(route.request().url()).origin}/integrations?connected=1`,
    });
  });

  const firstDisconnect = deferred();
  let disconnectCalls = 0;
  await page.route("**/api/integrations/composio/disconnect/slack", async (route) => {
    disconnectCalls += 1;
    mutations.push({
      path: new URL(route.request().url()).pathname,
      method: route.request().method(),
      body: await route.request().postDataJSON(),
      org: await route.request().headerValue("x-org-id"),
    });
    if (disconnectCalls === 1) {
      await firstDisconnect.promise;
      return json(route, { detail: "Revoke unavailable" }, 503);
    }
    connected = false;
    return json(route, { deleted: 1 });
  });

  await page.goto("/integrations");
  const connect = page.getByRole("button", { name: "Connect Slack" }).first();
  await connect.click();
  await expect(connect).toBeDisabled();
  await connect.evaluate((button: HTMLButtonElement) => button.click());
  expect(connectCalls).toBe(1);
  firstConnect.resolve();
  await expect(
    page.getByText(
      "Couldn't reach the server to start authorization. Try again in a moment.",
      { exact: true }
    )
  ).toBeVisible();
  expect(connected).toBe(false);

  await connect.click();
  await expect(page.getByText(/Connected\. Click .*Sync now.*index its content/)).toBeVisible();
  await expect(page).toHaveURL(/\/integrations$/);
  await expect(page.getByText("Connected as qa-slack@example.com")).toBeVisible();

  await page.getByRole("button", { name: "Manage" }).click();
  const manager = page.getByRole("dialog", { name: "Slack" });
  const disconnect = manager.getByRole("button", { name: "Disconnect Slack" });
  page.once("dialog", (confirmation) => confirmation.accept());
  await disconnect.click();
  await expect(disconnect).toBeDisabled();
  await disconnect.evaluate((button: HTMLButtonElement) => button.click());
  expect(disconnectCalls).toBe(1);
  firstDisconnect.resolve();
  await expect(manager.getByRole("alert")).toContainText("Couldn't disconnect");
  await expect(manager.getByText("Connected as qa-slack@example.com")).toBeVisible();
  expect(connected).toBe(true);

  page.once("dialog", (confirmation) => confirmation.accept());
  await disconnect.click();
  await expect(manager.getByText("Not connected", { exact: true })).toBeVisible();
  await expect(manager.getByRole("button", { name: "Connect Slack" })).toBeVisible();
  await expect(manager.getByRole("status")).toContainText("Disconnected");
  expect(connected).toBe(false);

  expect(mutations).toEqual([
    {
      path: "/api/integrations/composio/connect/slack",
      method: "POST",
      body: {},
      org: "qa-org",
    },
    {
      path: "/api/integrations/composio/connect/slack",
      method: "POST",
      body: {},
      org: "qa-org",
    },
    {
      path: "/api/integrations/composio/disconnect/slack",
      method: "POST",
      body: {},
      org: "qa-org",
    },
    {
      path: "/api/integrations/composio/disconnect/slack",
      method: "POST",
      body: {},
      org: "qa-org",
    },
  ]);
});
