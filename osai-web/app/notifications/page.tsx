"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, Check, RefreshCw } from "lucide-react";
import {
  getNotificationPage,
  markAllNotificationsRead,
  markNotificationRead,
  type AppNotification,
} from "@/lib/api";
import { announceNotificationsChanged } from "@/lib/notification-events";

const PAGE_SIZE = 25;

function notificationPresentation(notification: AppNotification) {
  if (notification.type === "thread.mention") {
    return {
      text: `${notification.payload.mentioned_by ?? "A teammate"} mentioned you in ${notification.payload.title ?? "a thread"}.`,
      href: notification.payload.thread_id
        ? `/ask?thread=${encodeURIComponent(notification.payload.thread_id)}`
        : null,
      action: "Open thread",
    };
  }
  if (notification.type === "document.shared") {
    return {
      text: `${notification.payload.shared_by ?? "A teammate"} shared ${notification.payload.title ?? "a file"} with you.`,
      href: "/ask",
      action: "Open Ask",
    };
  }
  return {
    text: notification.payload.title ?? "You have a workspace notification.",
    href: null,
    action: null,
  };
}

function mergeLatest(current: AppNotification[], latest: AppNotification[]) {
  const currentById = new Map(current.map((item) => [item.id, item]));
  const latestIds = new Set(latest.map((item) => item.id));
  const refreshed = latest.map((item) =>
    currentById.get(item.id)?.read ? { ...item, read: true } : item
  );
  return [...refreshed, ...current.filter((item) => !latestIds.has(item.id))];
}

export default function NotificationsPage() {
  const [items, setItems] = useState<AppNotification[]>([]);
  const itemsRef = useRef<AppNotification[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [refreshError, setRefreshError] = useState("");
  const [loadMoreError, setLoadMoreError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    setActionError("");
    setRefreshError("");
    setLoadMoreError("");
    try {
      const page = await getNotificationPage(PAGE_SIZE, undefined, false, true);
      itemsRef.current = page.items;
      setItems(page.items);
      setNextCursor(page.next_cursor);
      setTotal(page.total);
      setUnreadCount(page.unread_count);
    } catch {
      setLoadError("Notifications could not be loaded. Check your connection and retry.");
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshLatest = useCallback(async () => {
    try {
      const page = await getNotificationPage(PAGE_SIZE, undefined, false, true);
      setRefreshError("");
      const boundaryWasLoaded = page.next_cursor
        ? itemsRef.current.some((item) => item.id === page.next_cursor)
        : true;
      const merged = mergeLatest(itemsRef.current, page.items);
      itemsRef.current = merged;
      setItems(merged);
      setNextCursor((current) =>
        merged.length >= page.total
          ? null
          : boundaryWasLoaded && current
            ? current
            : page.next_cursor
      );
      setTotal(page.total);
      setUnreadCount(page.unread_count);
    } catch {
      setRefreshError("Notifications could not be refreshed. Your loaded history is unchanged.");
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void refreshLatest(), 30_000);
    return () => window.clearInterval(timer);
  }, [load, refreshLatest]);

  async function loadMore() {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setLoadMoreError("");
    try {
      const page = await getNotificationPage(PAGE_SIZE, nextCursor, false, true);
      const existing = new Set(itemsRef.current.map((item) => item.id));
      const merged = [
        ...itemsRef.current,
        ...page.items.filter((item) => !existing.has(item.id)),
      ];
      itemsRef.current = merged;
      setItems(merged);
      setNextCursor(page.next_cursor);
      setTotal(page.total);
      setUnreadCount(page.unread_count);
    } catch {
      setLoadMoreError("More notifications could not be loaded. Please retry.");
    } finally {
      setLoadingMore(false);
    }
  }

  async function markRead(notification: AppNotification) {
    if (notification.read) return;
    setActionError("");
    try {
      await markNotificationRead(notification.id);
      const updated = itemsRef.current.map((item) =>
        item.id === notification.id ? { ...item, read: true } : item
      );
      itemsRef.current = updated;
      setItems(updated);
      const nextUnreadCount = Math.max(0, unreadCount - 1);
      setUnreadCount(nextUnreadCount);
      announceNotificationsChanged(nextUnreadCount);
    } catch {
      setActionError("That notification could not be marked as read. Please retry.");
    }
  }

  async function markAllRead() {
    if (unreadCount === 0 || markingAll) return;
    setMarkingAll(true);
    setActionError("");
    try {
      await markAllNotificationsRead();
      const updated = itemsRef.current.map((item) => ({ ...item, read: true }));
      itemsRef.current = updated;
      setItems(updated);
      setUnreadCount(0);
      announceNotificationsChanged(0);
    } catch {
      setActionError("Notifications could not be marked as read. Please retry.");
    } finally {
      setMarkingAll(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Notifications</h1>
          <p>Shares and mentions that need your attention. This page refreshes automatically.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {unreadCount > 0 && (
            <button
              type="button"
              className="btn"
              onClick={() => void markAllRead()}
              disabled={markingAll || loading}
            >
              <Check className="size-3.5" aria-hidden="true" />
              {markingAll ? "Marking..." : "Mark all read"}
            </button>
          )}
          <button
            type="button"
            className="btn"
            onClick={() => void load()}
            disabled={loading || markingAll}
          >
            <RefreshCw className="size-3.5" aria-hidden="true" /> Refresh
          </button>
        </div>
      </div>

      {actionError && <div className="card error-text" role="alert">{actionError}</div>}
      {refreshError && <div className="card error-text" role="alert">{refreshError}</div>}
      {loadError ? (
        <div className="card async-state" role="alert">
          <div>
            <p className="error-text" style={{ marginBottom: 12 }}>{loadError}</p>
            <button type="button" className="btn btn-primary" onClick={() => void load()}>Retry</button>
          </div>
        </div>
      ) : loading ? (
        <div className="card async-state" role="status">Loading notifications...</div>
      ) : items.length === 0 ? (
        <div className="card async-state">
          <Bell className="size-5" aria-hidden="true" />
          <p>No notifications yet.</p>
        </div>
      ) : (
        <>
          <p className="meta" style={{ marginBottom: 12 }}>
            Showing {items.length.toLocaleString()} of {total.toLocaleString()} notifications · {unreadCount.toLocaleString()} unread
          </p>
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            {items.map((item) => {
              const presentation = notificationPresentation(item);
              return (
                <div key={item.id} style={{ display: "flex", gap: 12, alignItems: "center", padding: "14px 16px", borderBottom: "1px solid var(--border)", opacity: item.read ? 0.7 : 1 }}>
                  <Bell className="size-4 shrink-0" aria-hidden="true" />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{ margin: 0 }}>{presentation.text}</p>
                    {item.created_at && <time className="meta" dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time>}
                  </div>
                  {presentation.href && presentation.action && (
                    <Link href={presentation.href} className="btn">{presentation.action}</Link>
                  )}
                  <button type="button" className="btn" onClick={() => void markRead(item)} disabled={item.read || markingAll} aria-label={`Mark ${item.payload.title ?? "notification"} as read`}>
                    <Check className="size-3.5" aria-hidden="true" /> {item.read ? "Read" : "Mark read"}
                  </button>
                </div>
              );
            })}
          </div>
          {loadMoreError && <p className="error-text" role="alert">{loadMoreError}</p>}
          {nextCursor && (
            <div style={{ display: "flex", justifyContent: "center", marginTop: 16 }}>
              <button type="button" className="btn" onClick={() => void loadMore()} disabled={loadingMore}>
                {loadingMore ? "Loading..." : "Load more"}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
