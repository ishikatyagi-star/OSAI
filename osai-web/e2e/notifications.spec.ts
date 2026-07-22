import { expect, test } from "@playwright/test";
import { mockExternalFonts } from "./helpers";

const notice = (
  id: string,
  type: string,
  payload: Record<string, string>,
  read = false
) => ({
  id,
  type,
  payload,
  read,
  created_at: "2026-07-22T10:00:00Z",
});

test("notifications paginate, deep-link by type, and only mark read explicitly", async ({ page }) => {
  await mockExternalFonts(page);
  await page.addInitScript(() => {
    localStorage.setItem("osai_authed", "1");
    localStorage.setItem("osai_org_id", "qa-org");
    localStorage.setItem("osai_org_name", "QA Workspace");
  });

  let markCalls = 0;
  let markAllCalls = 0;
  await page.route("**/api/notifications/page?**", (route) => {
    const params = new URL(route.request().url()).searchParams;
    const sidebar = params.get("unread_only") === "true";
    const cursor = params.get("cursor");
    const items = sidebar
      ? [notice("mention", "thread.mention", { thread_id: "thread-2", title: "Launch plan" })]
      : cursor
        ? [notice("share", "document.shared", { title: "Roadmap", shared_by: "Ada" })]
        : [
            notice("mention", "thread.mention", {
              thread_id: "thread-2",
              title: "Launch plan",
              mentioned_by: "Grace",
            }),
            notice("system", "system.complete", { title: "Maintenance complete" }, true),
          ];
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items,
        next_cursor: !sidebar && !cursor ? "system" : null,
        total: 3,
        unread_count: 2,
      }),
    });
  });
  await page.route("**/api/notifications/mention/read", (route) => {
    markCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...notice("mention", "thread.mention", {}), read: true }),
    });
  });
  await page.route("**/api/notifications/read-all", (route) => {
    markAllCalls += 1;
    if (markAllCalls === 1) {
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Try again" }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ updated: 1 }),
    });
  });
  await page.route(
    (url) => url.pathname.endsWith("/api/notifications"),
    (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/threads/thread-2", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "thread-2",
        title: "Launch plan",
        shared: true,
        created_by: "grace",
        created_by_name: "Grace",
        created_at: "2026-07-22T10:00:00Z",
        updated_at: "2026-07-22T10:00:00Z",
        turns: [],
      }),
    })
  );

  await page.goto("/notifications");
  await expect(page.getByText("Showing 2 of 3 notifications · 2 unread")).toBeVisible();
  await expect(page.getByText("Maintenance complete")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open thread" })).toHaveAttribute(
    "href",
    "/ask?thread=thread-2"
  );
  await expect(page.locator(".sidebar-nav-badge").first()).toHaveText("2");

  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.getByText("Showing 3 of 3 notifications · 2 unread")).toBeVisible();
  await expect(page.getByText("Ada shared Roadmap with you.")).toBeVisible();

  await page.getByRole("link", { name: "Open thread" }).click();
  await expect(page).toHaveURL(/\/ask\?thread=thread-2$/);
  expect(markCalls).toBe(0);

  await page.goBack();
  await expect(page.getByRole("heading", { name: "Notifications" })).toBeVisible();
  await page.getByRole("button", { name: "Mark Launch plan as read" }).click();
  await expect(page.getByRole("button", { name: "Mark Launch plan as read" })).toBeDisabled();
  await expect(page.locator(".sidebar-nav-badge").first()).toHaveText("1");
  expect(markCalls).toBe(1);

  await page.getByRole("button", { name: "Mark all read" }).click();
  await expect(
    page.getByText("Notifications could not be marked as read. Please retry.")
  ).toBeVisible();
  await expect(page.getByText(/1 unread$/)).toBeVisible();
  await expect(page.locator(".sidebar-nav-badge").first()).toHaveText("1");
  await expect(page.getByRole("button", { name: "Mark all read" })).toBeEnabled();

  await page.getByRole("button", { name: "Mark all read" }).click();
  await expect(page.getByText(/0 unread$/)).toBeVisible();
  await expect(page.locator(".sidebar-nav-badge")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Mark all read" })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Mark Maintenance complete as read" })
  ).toBeDisabled();
  expect(markAllCalls).toBe(2);
});
