import { expect, test } from "@playwright/test";
import {
  mockEmptyNotificationInbox,
  mockExternalFonts,
  watchRuntimeIssues,
} from "./helpers";

const summary = {
  total_runs: 3,
  status_counts: { succeeded: 2, failed: 1 },
  documents_seen: 18,
  documents_indexed: 12,
  by_connector: {
    notion: {
      total_runs: 2,
      status_counts: { succeeded: 2 },
      documents_seen: 13,
      documents_indexed: 12,
    },
    slack: {
      total_runs: 1,
      status_counts: { failed: 1 },
      documents_seen: 5,
      documents_indexed: 0,
    },
  },
};

const run = (id: string, connector_key: string, status: string, indexed: number) => ({
  id,
  connector_key,
  status,
  started_at: "2026-07-21T10:00:00",
  documents_seen: indexed || 5,
  documents_indexed: indexed,
  error: status === "failed" ? "QA failure" : null,
});

test("Sync Runs labels all-time aggregates and cursor-loads the full history", async ({ page }) => {
  await mockExternalFonts(page);
  await mockEmptyNotificationInbox(page);
  await page.addInitScript(() => {
    localStorage.setItem("osai_authed", "1");
    localStorage.setItem("osai_org_id", "qa-org");
    localStorage.setItem("osai_org_name", "QA Workspace");
  });
  await page.route("**/api/dashboard/metrics", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total_documents: 9,
        documents_by_connector: { notion: 9 },
        documents_by_tier: { normal: 9 },
        connectors_connected: 1,
        sync_runs_total: 3,
        sync_runs_succeeded: 2,
        last_sync_at: null,
        members: 1,
        departments: 0,
        automations: 0,
      }),
    })
  );
  await page.route("**/api/sync-runs/page?**", (route) => {
    const cursor = new URL(route.request().url()).searchParams.get("cursor");
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: cursor
          ? [run("run-1", "notion", "succeeded", 5)]
          : [run("run-3", "notion", "succeeded", 7), run("run-2", "slack", "failed", 0)],
        next_cursor: cursor ? null : "run-2",
        summary,
        as_of: "2026-07-21T10:00:00Z",
      }),
    });
  });

  const runtime = watchRuntimeIssues(page);
  await page.goto("/sync-runs");

  await expect(page.getByRole("heading", { name: "Sync Runs" })).toBeVisible();
  await expect(page.getByText("Showing 2 of 3 runs")).toBeVisible();
  await expect(page.getByText("2 runs · 12 indexed")).toBeVisible();
  await expect(page.getByText("1 run · 0 indexed")).toBeVisible();
  await expect(page.locator(".timeline-card")).toHaveCount(2);

  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.getByText("Showing 3 of 3 runs")).toBeVisible();
  await expect(page.locator(".timeline-card")).toHaveCount(3);
  await expect(page.getByRole("button", { name: "Load more" })).toHaveCount(0);
  runtime.expectClean();
});
