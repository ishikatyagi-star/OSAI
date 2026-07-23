import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const [page, sidebar, api, ask] = await Promise.all([
  read("app/notifications/page.tsx"),
  read("components/sidebar.tsx"),
  read("lib/api.ts"),
  read("app/ask/page.tsx"),
]);

test("notification history uses the paginated inbox contract", () => {
  assert.match(api, /export type NotificationPage = \{[\s\S]*next_cursor[\s\S]*unread_count/);
  assert.match(page, /getNotificationPage\(PAGE_SIZE, nextCursor, false, true\)/);
  assert.match(page, /boundaryWasLoaded[\s\S]*merged\.length >= page\.total[\s\S]*page\.next_cursor/);
  assert.match(page, /loadError \? \([\s\S]*Retry[\s\S]*\) : loading \? \(/);
});

test("notification navigation is type-aware and does not mark read", () => {
  assert.match(page, /`\/ask\?thread=\$\{encodeURIComponent\(notification\.payload\.thread_id\)\}`/);
  assert.match(page, /notification\.type === "document\.shared"[\s\S]*href: "\/ask"/);
  assert.match(page, /You have a workspace notification/);
  assert.match(page, /<Link href=\{presentation\.href\} className="btn">\{presentation\.action\}<\/Link>/);
  assert.doesNotMatch(page, /<Link[^>]+onClick=\{\(\) => void markRead/);
});

test("read state changes only after the server acknowledges it", () => {
  const askMark = ask.indexOf("await markNotificationRead(id)");
  const askRemove = ask.indexOf("setShareNotices", askMark);
  assert.ok(askMark > -1 && askRemove > askMark);

  const markAll = page.indexOf("await markAllNotificationsRead()");
  const clearUnread = page.indexOf("setUnreadCount(0)", markAll);
  assert.ok(markAll > -1 && clearUnread > markAll);
  assert.match(api, /markAllNotificationsRead[\s\S]*"\/notifications\/read-all"/);
  assert.match(page, /onClick=\{\(\) => void markAllRead\(\)\}/);
  assert.match(page, /Notifications could not be marked as read\. Please retry\./);

  assert.match(ask, /That notification could not be marked as read\. Please retry\./);
  assert.match(sidebar, /getNotificationPage\(1, undefined, true, true\)/);
  assert.match(sidebar, /item\.href === "\/notifications" \? unreadCount/);
});
