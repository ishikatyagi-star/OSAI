import { expect, test, type Page } from "@playwright/test";
import { mockEmptyNotificationInbox, mockExternalFonts } from "./helpers";

const SOURCE_ID = "sql-source-qa";
const SOURCE_NAME = "QA warehouse";
const SOURCE_DSN = "postgresql://qa_user:qa_password@db.example.test:5432/qa";
const QUESTION = "How many users are in each status?";
const SQL = "SELECT status, COUNT(*) AS total FROM users GROUP BY status LIMIT 500";

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function session() {
  return {
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
  };
}

async function seedSignedInAdmin(page: Page) {
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
      body: JSON.stringify(session()),
    })
  );
}

test("admin completes the SQL API lifecycle with truthful retries and cleanup", async ({
  page,
}) => {
  await seedSignedInAdmin(page);

  const sourceCreateGate = deferred();
  const executeGate = deferred();
  const artifactGate = deferred();
  const sourceDeleteGate = deferred();
  const sourceCreateBodies: unknown[] = [];
  const planBodies: unknown[] = [];
  const executeBodies: unknown[] = [];
  const artifactBodies: unknown[] = [];
  let sources: Array<{ id: string; name: string; dsn: string }> = [];
  let sourceListCalls = 0;
  let sourceCreateCalls = 0;
  let schemaCalls = 0;
  let executeCalls = 0;
  let artifactCalls = 0;
  let sourceDeleteCalls = 0;
  let artifactDeleteCalls = 0;
  let artifactSaved = false;

  await page.route("**/api/sql/sources", async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      expect(request.postData()).toBeNull();
      sourceListCalls += 1;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(sources),
      });
    }

    expect(request.method()).toBe("POST");
    sourceCreateCalls += 1;
    sourceCreateBodies.push(await request.postDataJSON());
    if (sourceCreateCalls === 1) {
      await sourceCreateGate.promise;
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "SQL source store unavailable" }),
      });
    }
    sources = [
      {
        id: SOURCE_ID,
        name: SOURCE_NAME,
        dsn: "postgresql://qa_user:***@db.example.test:5432/qa",
      },
    ];
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(sources[0]),
    });
  });

  await page.route(`**/api/sql/sources/${SOURCE_ID}/schema`, (route) => {
    const request = route.request();
    expect(request.method()).toBe("GET");
    expect(new URL(request.url()).pathname).toBe(`/api/sql/sources/${SOURCE_ID}/schema`);
    expect(request.postData()).toBeNull();
    schemaCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          table: "users",
          columns: [
            { name: "status", type: "VARCHAR" },
            { name: "id", type: "UUID" },
          ],
        },
      ]),
    });
  });

  await page.route("**/api/sql/plan", async (route) => {
    expect(route.request().method()).toBe("POST");
    planBodies.push(await route.request().postDataJSON());
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        sql: SQL,
        explanation: "Counts users grouped by their current status.",
      }),
    });
  });

  await page.route("**/api/sql/execute", async (route) => {
    expect(route.request().method()).toBe("POST");
    executeCalls += 1;
    executeBodies.push(await route.request().postDataJSON());
    if (executeCalls === 1) {
      await executeGate.promise;
      return route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: "SQL query failed." }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        sql: SQL,
        columns: ["status", "total"],
        rows: [
          ["active", 42],
          ["inactive", 3],
        ],
        row_count: 2,
      }),
    });
  });

  await page.route("**/api/artifacts", async (route) => {
    expect(route.request().method()).toBe("POST");
    artifactCalls += 1;
    const body = await route.request().postDataJSON();
    artifactBodies.push(body);
    if (artifactCalls === 1) {
      await artifactGate.promise;
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Artifact store unavailable" }),
      });
    }
    artifactSaved = true;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "sql-artifact-qa",
        thread_id: null,
        title: QUESTION,
        kind: "source_table",
        data: (body as { data: unknown }).data,
        created_by_name: "qa@example.test",
        created_at: "2026-07-22T10:00:00Z",
      }),
    });
  });

  await page.route(`**/api/artifacts/sql-artifact-qa`, (route) => {
    expect(route.request().method()).toBe("DELETE");
    expect(route.request().postData()).toBeNull();
    artifactDeleteCalls += 1;
    artifactSaved = false;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ deleted: true }),
    });
  });

  await page.route(`**/api/sql/sources/${SOURCE_ID}`, async (route) => {
    const request = route.request();
    expect(request.method()).toBe("DELETE");
    expect(request.postData()).toBeNull();
    sourceDeleteCalls += 1;
    if (sourceDeleteCalls === 1) {
      await sourceDeleteGate.promise;
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "SQL source store unavailable" }),
      });
    }
    sources = [];
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ deleted: true }),
    });
  });

  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto("/sql");

  await expect(page.getByRole("heading", { name: "Data" })).toBeVisible();
  await expect(page.getByText(/No data sources yet/)).toBeVisible();
  await page.getByRole("button", { name: "Add source" }).click();
  await page.getByLabel("Source name").fill(SOURCE_NAME);
  await page.getByLabel("Read-only PostgreSQL connection string").fill(SOURCE_DSN);

  const addSourcePanel = page.locator(".card").filter({
    has: page.getByLabel("Source name"),
  });
  const connect = addSourcePanel.locator("button").last();
  await connect.click();
  await expect(connect).toBeDisabled();
  await connect.evaluate((button: HTMLButtonElement) => button.click());
  expect(sourceCreateCalls).toBe(1);

  sourceCreateGate.resolve();
  await expect(addSourcePanel.getByRole("alert")).toHaveText(
    "Could not add the source. Verify the read-only connection details and try again."
  );
  await expect(connect).toBeEnabled();
  await expect(page.getByLabel("Read-only PostgreSQL connection string")).toHaveValue(SOURCE_DSN);
  expect(sourceCreateCalls).toBe(1);

  await connect.click();
  await expect(page.locator('select[aria-label="Data source"]')).toHaveValue(SOURCE_ID);
  await expect(page.getByRole("option", { name: SOURCE_NAME })).toBeAttached();
  await expect(page.getByText(SOURCE_DSN, { exact: true })).toHaveCount(0);
  expect(sourceListCalls).toBe(2);
  expect(sourceCreateBodies).toEqual([
    { name: SOURCE_NAME, dsn: SOURCE_DSN },
    { name: SOURCE_NAME, dsn: SOURCE_DSN },
  ]);

  const schema = await page.evaluate(async (sourceId) => {
    const response = await fetch(`/api/sql/sources/${sourceId}/schema`, {
      credentials: "include",
    });
    return { status: response.status, body: await response.json() };
  }, SOURCE_ID);
  expect(schema).toEqual({
    status: 200,
    body: [
      {
        table: "users",
        columns: [
          { name: "status", type: "VARCHAR" },
          { name: "id", type: "UUID" },
        ],
      },
    ],
  });
  expect(schemaCalls).toBe(1);

  await page.getByPlaceholder(/How many documents were ingested/).fill(QUESTION);
  await page.getByRole("button", { name: "Plan" }).click();
  await expect(page.getByText("Counts users grouped by their current status.")).toBeVisible();
  await expect(page.getByLabel("Generated SQL (editable)")).toHaveValue(SQL);
  expect(planBodies).toEqual([{ source_id: SOURCE_ID, question: QUESTION }]);

  const run = page.getByRole("button", { name: "Run query" });
  await run.click();
  await expect(run).toBeDisabled();
  await run.evaluate((button: HTMLButtonElement) => button.click());
  expect(executeCalls).toBe(1);

  executeGate.resolve();
  await expect(
    page.getByText("The read-only query failed. Review the SQL and try again.", {
      exact: true,
    })
  ).toBeVisible();
  await expect(page.getByLabel("Generated SQL (editable)")).toHaveValue(SQL);
  await expect(page.getByRole("region", { name: "SQL query results" })).toHaveCount(0);
  await expect(run).toBeEnabled();
  expect(executeCalls).toBe(1);

  await run.click();
  const results = page.getByRole("region", { name: "SQL query results" });
  await expect(results).toBeVisible();
  await expect(page.getByText("2 rows", { exact: true })).toBeVisible();
  await expect(results.getByRole("columnheader", { name: "status" })).toBeVisible();
  await expect(results.getByRole("columnheader", { name: "total" })).toBeVisible();
  await expect(results.getByRole("cell", { name: "active", exact: true })).toBeVisible();
  await expect(results.getByRole("cell", { name: "42" })).toBeVisible();
  expect(executeBodies).toEqual([
    { source_id: SOURCE_ID, sql: SQL },
    { source_id: SOURCE_ID, sql: SQL },
  ]);

  const save = page.getByRole("button", { name: "Save as artifact" });
  await save.click();
  await expect(page.getByRole("button", { name: "Saving..." })).toBeDisabled();
  await page
    .getByRole("button", { name: "Saving..." })
    .evaluate((button: HTMLButtonElement) => button.click());
  expect(artifactCalls).toBe(1);

  artifactGate.resolve();
  await expect(
    page.getByText("The result could not be saved as an artifact. Please try again.", {
      exact: true,
    })
  ).toBeVisible();
  await expect(save).toBeEnabled();
  expect(artifactCalls).toBe(1);

  await save.click();
  await expect(page.getByRole("button", { name: "Saved" })).toBeDisabled();
  expect(artifactCalls).toBe(2);
  for (const body of artifactBodies) {
    expect(body).toEqual({
      title: QUESTION,
      kind: "source_table",
      data: {
        id: expect.stringMatching(/^sql-\d+$/),
        kind: "source_table",
        title: QUESTION,
        subtitle: SQL,
        rows: [
          { label: "active", value: "42", tone: "neutral" },
          { label: "inactive", value: "3", tone: "neutral" },
        ],
      },
    });
  }
  expect(artifactSaved).toBe(true);

  await page.getByRole("button", { name: `Remove source: ${SOURCE_NAME}` }).click();
  const dialog = page.getByRole("dialog", { name: "Remove this data source?" });
  await expect(dialog).toBeVisible();
  const remove = dialog.locator("button.btn-danger");
  await remove.click();
  await expect(remove).toBeDisabled();
  await remove.evaluate((button: HTMLButtonElement) => button.click());
  expect(sourceDeleteCalls).toBe(1);

  sourceDeleteGate.resolve();
  await expect(dialog.getByRole("alert")).toHaveText(
    "The data source could not be removed. Please try again."
  );
  await expect(remove).toBeEnabled();
  await expect(page.locator('select[aria-label="Data source"]')).toHaveValue(SOURCE_ID);
  expect(sourceDeleteCalls).toBe(1);

  await remove.click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText(/No data sources yet/)).toBeVisible();
  expect(sourceDeleteCalls).toBe(2);
  expect(sources).toEqual([]);

  const artifactCleanup = await page.evaluate(async () => {
    const response = await fetch("/api/artifacts/sql-artifact-qa", {
      method: "DELETE",
      credentials: "include",
    });
    return { status: response.status, body: await response.json() };
  });
  expect(artifactCleanup).toEqual({ status: 200, body: { deleted: true } });
  expect(artifactDeleteCalls).toBe(1);
  expect(artifactSaved).toBe(false);
  expect(pageErrors).toEqual([]);
});
