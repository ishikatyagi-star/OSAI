import { expect, test } from "@playwright/test";
import { mockExternalFonts } from "./helpers";

const metrics = {
  total_documents: 0,
  documents_by_connector: {},
  documents_by_tier: {},
  connectors_connected: 0,
  sync_runs_total: 0,
  sync_runs_succeeded: 0,
  last_sync_at: null,
  members: 1,
  departments: 0,
  automations: 0,
};

const validArtifact = (id: string, title: string) => ({
  id,
  thread_id: null,
  title,
  kind: "source_table",
  data: {
    id: `openui-${id}`,
    kind: "source_table",
    title,
    subtitle: null,
    metrics: null,
    rows: [{ label: "Ticket", value: "Open", meta: null, tone: "neutral" }],
  },
  created_by_name: "qa@example.test",
  created_at: "2026-07-22T10:00:00Z",
});

test("Artifacts safely renders legacy JSON, retries deletion, and loads every page", async ({
  page,
}) => {
  await mockExternalFonts(page);
  await page.addInitScript(() => {
    localStorage.setItem("osai_authed", "1");
    localStorage.setItem("osai_org_id", "qa-org");
    localStorage.setItem("osai_org_name", "QA Workspace");
  });
  await page.route("**/api/dashboard/metrics", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(metrics) })
  );
  await page.route("**/api/notifications/page?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null, total: 0, unread_count: 0 }),
    })
  );

  const malformed = {
    ...validArtifact("malformed", "Malformed legacy"),
    data: { id: "legacy", kind: "source_table", title: "Legacy", rows: "not-an-array" },
  };
  let wasDeleted = false;
  await page.route("**/api/artifacts/page?**", (route) => {
    const cursor = new URL(route.request().url()).searchParams.get("cursor");
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: cursor
          ? [validArtifact("oldest", "Oldest reachable artifact")]
          : [malformed, validArtifact("recent", "Recent artifact")],
        next_cursor: cursor ? null : "recent",
        total: wasDeleted ? 2 : 3,
      }),
    });
  });

  let deleteAttempts = 0;
  await page.route("**/api/artifacts/malformed", (route) => {
    deleteAttempts += 1;
    if (deleteAttempts === 1) return route.abort("failed");
    wasDeleted = true;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ deleted: true }),
    });
  });

  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto("/artifacts");

  await expect(page.getByRole("heading", { name: "Artifacts" })).toBeVisible();
  await expect(page.getByText("Showing 2 of 3 saved artifacts.")).toBeVisible();
  await expect(page.getByText("Unsupported artifact")).toBeVisible();
  await expect(page.getByRole("button", { name: "Delete Malformed legacy" })).toBeVisible();

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export" }).first().click();
  await expect((await download).suggestedFilename()).toBe("malformed-legacy.md");

  await page.getByRole("button", { name: "Delete Malformed legacy" }).click();
  await page.getByRole("button", { name: "Delete artifact" }).click();
  await expect(page.getByText("The artifact could not be deleted. Please try again.").last()).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Delete this artifact?" })).toBeVisible();

  await page.getByRole("button", { name: "Delete artifact" }).click();
  await expect(page.getByRole("button", { name: "Delete Malformed legacy" })).toHaveCount(0);
  expect(deleteAttempts).toBe(2);

  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.getByText("Showing 2 of 2 saved artifacts.")).toBeVisible();
  await expect(page.getByText("Oldest reachable artifact")).toBeVisible();
  await expect(page.getByRole("button", { name: "Load more" })).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});
