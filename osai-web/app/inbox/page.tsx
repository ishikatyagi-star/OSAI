"use client";

import { useState } from "react";
import { Check, User } from "lucide-react";
import { DEMO_INBOX_ITEMS, type InboxItem } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";

const TYPE_META: Record<InboxItem["type"], { label: string; cls: string }> = {
  blocker:   { label: "blocker",   cls: "tag-blocker" },
  "follow-up": { label: "follow-up", cls: "tag-follow-up" },
  priority:  { label: "priority",  cls: "tag-priority" },
  update:    { label: "update",    cls: "tag-update" },
};

export default function InboxPage() {
  const [items, setItems] = useState<InboxItem[]>(() =>
    isDemo() ? DEMO_INBOX_ITEMS : []
  );
  const [filter, setFilter] = useState<"all" | InboxItem["type"]>("all");
  const [statusFilter, setStatusFilter] = useState<"all" | "inbox" | "reviewed">("all");

  function setItemStatus(id: string, status: InboxItem["status"]) {
    setItems((prev) =>
      prev.map((i) => (i.id === id ? { ...i, status } : i))
    );
  }

  const filtered = items.filter((i) => {
    const typeMatch = filter === "all" || i.type === filter;
    const statusMatch = statusFilter === "all" || i.status === statusFilter;
    return typeMatch && statusMatch;
  });

  const inboxCount = items.filter((i) => i.status === "inbox").length;

  function exportCsv() {
    const cols: (keyof InboxItem)[] = [
      "type", "text", "source", "dept", "person", "date", "status",
    ];
    const esc = (v: string) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const rows = [
      cols.join(","),
      ...filtered.map((i) => cols.map((c) => esc(i[c] as string)).join(",")),
    ];
    const blob = new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `context-inbox-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Context Inbox</h1>
          <p>Synced context items from all connected sources - tag, review, or escalate.</p>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <span className="badge badge-red" style={{ alignSelf: "center" }}>{inboxCount} unreviewed</span>
          <button className="btn btn-primary" onClick={exportCsv} disabled={filtered.length === 0}>Export</button>
        </div>
      </div>

      {/* Filters - grouped and labelled so the active selection is unambiguous */}
      <div className="filter-bar">
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span className="filter-group-label">Type</span>
          {(["all", "blocker", "follow-up", "priority", "update"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setFilter(t)}
              className={`suggestion-chip${filter === t ? " active" : ""}`}
              aria-pressed={filter === t}
            >
              {t === "all" ? "All types" : t}
            </button>
          ))}
        </div>
        <div style={{ flex: 1, minWidth: 12 }} />
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span className="filter-group-label">Status</span>
          {(["all", "inbox", "reviewed"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`suggestion-chip${statusFilter === s ? " active" : ""}`}
              aria-pressed={statusFilter === s}
            >
              {s === "all" ? "All statuses" : s}
            </button>
          ))}
        </div>
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
                <span><User size={12} style={{ display: "inline", verticalAlign: "middle", marginRight: 3 }} />{item.person}</span>
              </div>

              <div className="context-item-actions">
                {item.status === "inbox" ? (
                  <>
                    <button
                      className="btn btn-primary btn-xs"
                      onClick={() => setItemStatus(item.id, "reviewed")}
                    >
                      Mark Reviewed
                    </button>
                    <button className="btn btn-xs">
                      Add to Decision Log
                    </button>
                    <button className="btn btn-xs">
                      Create Task
                    </button>
                  </>
                ) : (
                  <>
                    <span
                      className="meta font-semibold"
                      style={{ display: "inline-flex", alignItems: "center", gap: 5, color: "var(--green)", fontSize: 11 }}
                    >
                      <Check size={12} strokeWidth={2} /> Reviewed
                    </span>
                    <button
                      className="btn btn-ghost btn-xs"
                      onClick={() => setItemStatus(item.id, "inbox")}
                    >
                      Reopen
                    </button>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
