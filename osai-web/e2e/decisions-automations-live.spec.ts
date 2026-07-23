import { expect, test, type Page, type Route } from "@playwright/test";
import type { ApiDecision, Automation } from "../lib/api";
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

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
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

async function choose(page: Page, label: string, option: string) {
  await page.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

test("signed-in Decisions persist create, edit, filters, and cleanup through the API", async ({
  page,
}) => {
  await seedSignedInWorkspace(page);

  let decisions: ApiDecision[] = [];
  const mutations: Array<{ method: string; path: string; body?: unknown }> = [];
  await page.route("**/api/decisions**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    const method = request.method();
    expect(await request.headerValue("x-org-id")).toBe("qa-org");

    if (method === "GET") return json(route, decisions);

    const body = method === "DELETE" ? undefined : await request.postDataJSON();
    mutations.push({ method, path: pathname, body });
    if (method === "POST" && pathname === "/api/decisions") {
      const input = body as Omit<ApiDecision, "id" | "identifiedBy" | "date" | "updated_at">;
      const created: ApiDecision = {
        ...input,
        id: "decision-live-1",
        identifiedBy: "source",
        date: "2026-07-22T10:00:00Z",
        updated_at: "2026-07-22T10:00:00Z",
      };
      decisions = [created];
      return json(route, created);
    }
    if (method === "PATCH" && pathname === "/api/decisions/decision-live-1") {
      decisions = [
        {
          ...decisions[0],
          ...(body as Partial<ApiDecision>),
          updated_at: "2026-07-22T10:05:00Z",
        },
      ];
      return json(route, decisions[0]);
    }
    if (method === "DELETE" && pathname === "/api/decisions/decision-live-1") {
      decisions = [];
      return json(route, { deleted: true });
    }
    throw new Error(`Unexpected Decisions request: ${method} ${pathname}`);
  });

  const title = "QA durable browser decision";
  const editedTitle = `${title} edited`;
  await page.goto("/decisions");
  await expect(page.getByText("No decisions yet.", { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "+ Add Decision" }).click();
  await page.getByPlaceholder("Decision title").fill(title);
  await choose(page, "Decision impact", "High");
  await page.getByPlaceholder("Owner").fill("QA Admin");
  await page.getByPlaceholder("Source").fill("Browser QA");
  await page.getByPlaceholder("architecture, security").fill("e2e, durable");
  await page.getByRole("button", { name: "Save decision" }).click();
  await expect(page.getByText(title, { exact: true })).toBeVisible();

  await page.getByLabel("Search decisions").fill(title);
  await choose(page, "Filter decisions by status", "Proposed");
  await choose(page, "Filter decisions by impact level", "High");
  await expect(page.getByText("1 of 1 decisions", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: `Edit decision: ${title}` }).click();
  await page.getByPlaceholder("Decision title").fill(editedTitle);
  await choose(page, "Decision status", "Approved");
  await choose(page, "Decision impact", "Critical");
  await page.getByPlaceholder("architecture, security").fill("e2e, edited");
  await page.getByRole("button", { name: "Save decision" }).click();
  await expect(page.getByText("0 of 1 decisions", { exact: true })).toBeVisible();

  await choose(page, "Filter decisions by status", "Approved");
  await choose(page, "Filter decisions by impact level", "Critical");
  await expect(page.getByText(editedTitle, { exact: true })).toBeVisible();

  await page.getByRole("button", { name: `Delete decision: ${editedTitle}` }).click();
  await page.getByRole("button", { name: "Delete decision", exact: true }).click();
  await expect(page.getByText(editedTitle, { exact: true })).toHaveCount(0);
  await expect(page.getByText("No decisions yet.", { exact: false })).toBeVisible();

  expect(decisions).toEqual([]);
  expect(mutations).toEqual([
    {
      method: "POST",
      path: "/api/decisions",
      body: {
        title,
        status: "proposed",
        impact: "high",
        owner: "QA Admin",
        source: "Browser QA",
        tags: ["e2e", "durable"],
      },
    },
    {
      method: "PATCH",
      path: "/api/decisions/decision-live-1",
      body: {
        title: editedTitle,
        status: "approved",
        impact: "critical",
        owner: "QA Admin",
        source: "Browser QA",
        tags: ["e2e", "edited"],
      },
    },
    { method: "DELETE", path: "/api/decisions/decision-live-1", body: undefined },
  ]);
});

test("signed-in Automations persist their lifecycle and tell the truth on a failed run", async ({
  page,
}) => {
  await seedSignedInWorkspace(page);
  await page.route("**/api/capabilities", (route) =>
    json(route, {
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
    })
  );
  await page.route("**/api/workflows", (route) => json(route, []));
  await page.route("**/api/integrations", (route) => json(route, []));

  let automations: Automation[] = [];
  let runCalls = 0;
  const firstRun = deferred();
  const mutations: Array<{ method: string; path: string; body?: unknown }> = [];
  await page.route("**/api/automations**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    const method = request.method();
    expect(await request.headerValue("x-org-id")).toBe("qa-org");

    if (method === "GET" && pathname === "/api/automations") return json(route, automations);

    const body = method === "DELETE" ? undefined : await request.postDataJSON();
    mutations.push({ method, path: pathname, body });
    if (method === "POST" && pathname === "/api/automations") {
      const input = body as Pick<Automation, "name" | "prompt" | "cadence">;
      const created: Automation = {
        ...input,
        id: "automation-live-1",
        enabled: true,
        status: "active",
        last_run_at: null,
        last_result: null,
        deliver_to: null,
        last_delivery: null,
        updated_at: "2026-07-22T11:00:00Z",
        has_trigger_token: false,
      };
      automations = [created];
      return json(route, created);
    }
    if (method === "PATCH" && pathname === "/api/automations/automation-live-1") {
      const patch = body as {
        name: string;
        prompt: string;
        cadence: Automation["cadence"];
        status: Automation["status"];
        deliver_to: Automation["deliver_to"];
      };
      automations = [
        { ...automations[0], ...patch, updated_at: "2026-07-22T11:05:00Z" },
      ];
      return json(route, automations[0]);
    }
    if (method === "POST" && pathname === "/api/automations/automation-live-1/run") {
      runCalls += 1;
      if (runCalls === 1) {
        await firstRun.promise;
        return json(route, { detail: "Runner unavailable" }, 503);
      }
      automations = [
        {
          ...automations[0],
          last_run_at: "2026-07-22T11:10:00Z",
          last_result: "QA manual run completed",
        },
      ];
      return json(route, { id: "automation-live-1", result: "QA manual run completed" });
    }
    if (pathname === "/api/automations/automation-live-1/token") {
      if (method === "POST") {
        automations = [{ ...automations[0], has_trigger_token: true }];
        return json(route, {
          token: "qa-trigger-token-shown-once",
          trigger_url: "/automations/automation-live-1/trigger",
        });
      }
      if (method === "DELETE") {
        automations = [{ ...automations[0], has_trigger_token: false }];
        return json(route, { revoked: true });
      }
    }
    if (method === "DELETE" && pathname === "/api/automations/automation-live-1") {
      automations = [];
      return json(route, { deleted: true });
    }
    throw new Error(`Unexpected Automations request: ${method} ${pathname}`);
  });

  const name = "QA durable automation";
  const editedName = `${name} edited`;
  await page.goto("/automations");
  await expect(page.getByText("No automations yet.", { exact: false })).toBeVisible();

  await page.getByLabel("Automation name").first().fill(name);
  await page.getByLabel("Automation task prompt").first().fill("Summarize unresolved blockers");
  await page.getByRole("button", { name: "Create automation" }).click();
  await expect(page.getByText(name, { exact: true })).toBeVisible();

  await page.getByRole("button", { name: `Edit automation: ${name}` }).click();
  const editForm = page.locator(".automation-edit-form");
  await editForm.getByLabel("Automation name").fill(editedName);
  await editForm.getByLabel("Automation task prompt").fill("Summarize blockers and owners");
  await editForm.getByRole("combobox", { name: "Automation status" }).click();
  await page.getByRole("option", { name: "paused", exact: true }).click();
  await editForm.getByLabel("Slack channel for results").fill("#qa-results");
  await editForm.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(editedName, { exact: true })).toBeVisible();
  await expect(page.getByText("paused", { exact: true })).toBeVisible();

  const run = page.getByRole("button", { name: `Run automation now: ${editedName}` });
  await run.click();
  await expect(run).toBeDisabled();
  await run.evaluate((button: HTMLButtonElement) => button.click());
  expect(runCalls).toBe(1);

  firstRun.resolve();
  await expect(page.locator(".card[role='alert']")).toHaveText(
    "The automation did not run. No result was saved; please try again."
  );
  await expect(page.getByText("QA manual run completed", { exact: true })).toHaveCount(0);
  expect(automations[0].last_result).toBeNull();
  expect(runCalls).toBe(1);

  await run.click();
  await expect(page.getByText("QA manual run completed", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".card[role='alert']")).toHaveCount(0);
  expect(runCalls).toBe(2);

  await page
    .getByRole("button", { name: `Create API trigger token for ${editedName}` })
    .click();
  await expect(page.getByText("qa-trigger-token-shown-once", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: `Revoke API trigger token for ${editedName}` })
    .click();
  await page.getByRole("button", { name: "Revoke token" }).click();
  await expect(page.getByText("qa-trigger-token-shown-once", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: `Create API trigger token for ${editedName}` })
  ).toBeVisible();

  await page.getByRole("button", { name: `Delete automation: ${editedName}` }).click();
  await page.getByRole("button", { name: "Delete automation", exact: true }).click();
  await expect(page.getByText(editedName, { exact: true })).toHaveCount(0);
  await expect(page.getByText("No automations yet.", { exact: false })).toBeVisible();

  expect(automations).toEqual([]);
  expect(mutations).toEqual([
    {
      method: "POST",
      path: "/api/automations",
      body: { name, prompt: "Summarize unresolved blockers", cadence: "manual" },
    },
    {
      method: "PATCH",
      path: "/api/automations/automation-live-1",
      body: {
        name: editedName,
        prompt: "Summarize blockers and owners",
        cadence: "manual",
        status: "paused",
        deliver_to: { channel: "slack", target: "#qa-results" },
      },
    },
    {
      method: "POST",
      path: "/api/automations/automation-live-1/run",
      body: {},
    },
    {
      method: "POST",
      path: "/api/automations/automation-live-1/run",
      body: {},
    },
    {
      method: "POST",
      path: "/api/automations/automation-live-1/token",
      body: {},
    },
    {
      method: "DELETE",
      path: "/api/automations/automation-live-1/token",
      body: undefined,
    },
    {
      method: "DELETE",
      path: "/api/automations/automation-live-1",
      body: undefined,
    },
  ]);
});
