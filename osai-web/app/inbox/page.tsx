"use client";

import { useState } from "react";
import { DEMO_INBOX_ITEMS, type InboxItem } from "@/lib/demo-data";

const TYPE_META: Record<InboxItem["type"], { label: string; cls: string }> = {
  blocker:   { label: "blocker",   cls: "tag-blocker" },
  "follow-up": { label: "follow-up", cls: "tag-follow-up" },
  priority:  { label: "priority",  cls: "tag-priority" },
  update:    { label: "update",    cls: "tag-update" },
};

export default function InboxPage() {
  const [items, setItems] = useState<InboxItem[]>(DEMO_INBOX_ITEMS);
  const [filter, setFilter] = useState<"all" | InboxItem["type"]>("all");
  const [statusFilter, setStatusFilter] = useState<"all" | "inbox" | "reviewed">("all");

  function markReviewed(id: string) {
    setItems((prev) =>
      prev.map((i) => (i.id === id ? { ...i, status: "reviewed" } : i))
    );
  }

  const filtered = items.filter((i) => {
    const typeMatch = filter === "all" || i.type === filter;
    const statusMatch = statusFilter === "all" || i.status === statusFilter;
    return typeMatch && statusMatch;
  });

  const inboxCount = items.filter((i) => i.status === "inbox").length;

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Context Inbox</h1>
          <p>Synced context items from all connected sources — tag, review, or escalate.</p>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <span className="badge badge-red" style={{ alignSelf: "center" }}>{inboxCount} unreviewed</span>
          <button className="btn btn-primary">Export</button>
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 8, marginBottom: 20, flexWrap: "wrap" }}>
        {(["all", "blocker", "follow-up", "priority", "update"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setFilter(t)}
            className={`suggestion-chip${filter === t ? " active" : ""}`}
          >
            {t === "all" ? "All types" : t}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        {(["all", "inbox", "reviewed"] as const).map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`suggestion-chip${statusFilter === s ? " active" : ""}`}
          >
            {s === "all" ? "All statuses" : s}
          </button>
        ))}
      </div>

      {/* Items */}
      {filtered.length === 0 && (
        <p className="empty-state">No items matching this filter.</p>
      )}

      <div className="card" style={{ padding: "0 20px" }}>
        {filtered.map((item) => {
          const tm = TYPE_META[item.type];
          return (
            <div key={item.id} className="context-item">
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className={`tag ${tm.cls}`}>{tm.label}</span>
                <span className={`badge ${item.status === "reviewed" ? "badge-grey" : "badge-blue"}`} style={{ fontSize: 10 }}>
                  {item.status}
                </span>
                <span className="meta" style={{ marginLeft: "auto" }}>{item.date}</span>
              </div>

              <p className="context-item-text">{item.text}</p>

              <div className="context-item-meta">
                <span>{item.source}</span>
                <span>·</span>
                <span>{item.dept}</span>
                <span>·</span>
                <span>👤 {item.person}</span>
              </div>

              <div className="context-item-actions">
                {item.status === "inbox" && (
                  <button
                    className="btn btn-primary"
                    style={{ fontSize: 11, padding: "5px 12px" }}
                    onClick={() => markReviewed(item.id)}
                  >
                    Mark Reviewed
                  </button>
                )}
                <button className="btn" style={{ fontSize: 11, padding: "5px 12px" }}>
                  Add to Decision Log
                </button>
                <button className="btn" style={{ fontSize: 11, padding: "5px 12px" }}>
                  Create Task
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
