"use client";

import { useState } from "react";
import Link from "next/link";
import { DEMO_WORKFLOW_RUNS, DEMO_STATS, DEMO_INBOX_ITEMS, DEMO_DECISIONS } from "@/lib/demo-data";

const ATTENTION_ITEMS = [
  {
    id: "a1",
    tag: "blocker",
    title: "Q3 roadmap document not accessible to engineering team",
    source: "Notion · Product Workspace",
    owner: "Priya Sharma",
    time: "2h ago",
  },
  {
    id: "a2",
    tag: "blocker",
    title: "Customer escalation ticket #FD-2891 unassigned for 48h",
    source: "Freshdesk · Support Queue",
    owner: "Unassigned",
    time: "48h ago",
  },
  {
    id: "a3",
    tag: "follow-up",
    title: "Partnership meeting notes not distributed to stakeholders",
    source: "Zoom · Recordings",
    owner: "Anish Mehta",
    time: "1d ago",
  },
];

export default function DashboardPage() {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [snoozed, setSnoozed] = useState<Set<string>>(new Set());

  const pendingActions = DEMO_WORKFLOW_RUNS
    .flatMap((r) => r.action_items ?? [])
    .filter((a) => a.status === "needs_review").length;

  const active = ATTENTION_ITEMS.filter(
    (i) => !dismissed.has(i.id) && !snoozed.has(i.id)
  );

  const pendingDecisions = DEMO_DECISIONS?.filter((d) => d.status === "proposed").length ?? 2;

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Dashboard</h1>
          <p>Good morning — here's what needs your attention today.</p>
        </div>
        <Link href="/inbox" className="btn btn-primary">
          + Add Context
        </Link>
      </div>

      {/* Gradient spotlight banner — framer signature atmosphere tile */}
      <div
        className="spotlight spotlight-violet"
        style={{
          marginBottom: 24,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 24,
          flexWrap: "wrap",
        }}
      >
        <div style={{ maxWidth: 560 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: 1.2,
              textTransform: "uppercase",
              color: "rgba(255,255,255,0.7)",
              marginBottom: 10,
            }}
          >
            Company pulse
          </div>
          <h2 style={{ fontSize: 30, lineHeight: 1.05, letterSpacing: "-1.4px", margin: 0 }}>
            Your company context, working for you.
          </h2>
          <p style={{ marginTop: 10, fontSize: 15, maxWidth: 480 }}>
            {DEMO_STATS.documentsIndexed.toLocaleString()} sources indexed across every connector — ask anything, surface blockers, and keep decisions moving.
          </p>
        </div>
        <Link
          href="/ask"
          className="btn btn-primary"
          style={{ flexShrink: 0 }}
        >
          Ask OSAI →
        </Link>
      </div>

      {/* Stat cards */}
      <div className="stats-grid">
        {[
          { label: "Active Blockers", value: active.filter(i => i.tag === "blocker").length, color: "var(--red)", link: "/inbox" },
          { label: "Pending Decisions", value: pendingDecisions, color: "var(--orange)", link: "/decisions" },
          { label: "Overdue Follow-ups", value: active.filter(i => i.tag === "follow-up").length, color: "var(--yellow)", link: "/board" },
          { label: "Context This Week", value: DEMO_STATS.documentsIndexed, color: "var(--teal)", link: "/inbox" },
        ].map((s) => (
          <Link key={s.label} href={s.link} className="stat-card" style={{ textDecoration: "none" }}>
            <div className="stat-card-label">{s.label}</div>
            <div className="stat-card-value" style={{ color: s.color }}>{s.value.toLocaleString()}</div>
          </Link>
        ))}
      </div>

      {/* Two-column layout */}
      <div className="dashboard-two-col" style={{ gap: 24 }}>
        {/* Needs Attention */}
        <div>
          <div className="section-header">
            <h2>Needs Attention</h2>
            <Link href="/inbox">View all →</Link>
          </div>

          {active.length === 0 && (
            <div className="card" style={{ textAlign: "center", padding: "32px 20px" }}>
              <p style={{ fontSize: 20, marginBottom: 8 }}>✓</p>
              <p style={{ color: "var(--green)", fontWeight: 600, fontSize: 13 }}>All clear!</p>
              <p className="meta" style={{ marginTop: 4 }}>No blockers or follow-ups right now.</p>
            </div>
          )}

          {active.map((item) => (
            <div key={item.id} className="attention-card">
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span className={`tag tag-${item.tag}`}>{item.tag}</span>
                <span className="meta" style={{ marginLeft: "auto" }}>{item.time}</span>
              </div>
              <div className="attention-card-title">{item.title}</div>
              <div className="attention-card-meta">
                <span>{item.source}</span>
                <span>·</span>
                <span>👤 {item.owner}</span>
              </div>
              <div className="attention-card-actions">
                <button className="attention-card-action" onClick={() => {}}>View Task</button>
                <span style={{ color: "var(--border)" }}>|</span>
                <button className="attention-card-action" onClick={() => setSnoozed(p => new Set([...p, item.id]))}>Snooze</button>
                <span style={{ color: "var(--border)" }}>|</span>
                <button className="attention-card-action dismiss" onClick={() => setDismissed(p => new Set([...p, item.id]))}>Dismiss</button>
              </div>
            </div>
          ))}
        </div>

        {/* Right column */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Recent decisions */}
          <div>
            <div className="section-header">
              <h2>Recent Decisions</h2>
              <Link href="/decisions">View all →</Link>
            </div>
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              {(DEMO_DECISIONS ?? []).slice(0, 4).map((d, i) => (
                <div
                  key={d.id}
                  className="activity-row"
                  style={{
                    padding: "12px 16px",
                    borderBottom: i < 3 ? "1px solid var(--border)" : "none",
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)", marginBottom: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {d.title}
                    </p>
                    <p className="meta">{d.owner} · {d.date}</p>
                  </div>
                  <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
                    <span className={`badge badge-${d.status === "approved" ? "green" : d.status === "rejected" ? "red" : "grey"}`}>
                      {d.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Connector health */}
          <div>
            <div className="section-header">
              <h2>Connector Health</h2>
              <Link href="/integrations">Manage →</Link>
            </div>
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              {[
                { key: "notion", icon: "📝", label: "Notion", docs: 847, status: "connected" },
                { key: "slack", icon: "💬", label: "Slack", docs: 302, status: "connected" },
                { key: "google_drive", icon: "📁", label: "Google Drive", docs: 98, status: "connected" },
                { key: "freshdesk", icon: "🎫", label: "Freshdesk", docs: 47, status: "connected" },
                { key: "zoom", icon: "📹", label: "Zoom", docs: 12, status: "connected" },
              ].map((c, i) => (
                <div
                  key={c.key}
                  className="activity-row"
                  style={{ padding: "10px 16px", borderBottom: i < 4 ? "1px solid var(--border)" : "none" }}
                >
                  <span style={{ fontSize: 15 }}>{c.icon}</span>
                  <div style={{ flex: 1 }}>
                    <p style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)", margin: 0 }}>{c.label}</p>
                    <p className="meta">{c.docs.toLocaleString()} docs indexed</p>
                  </div>
                  <span
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: "50%",
                      background: "var(--green)",
                      boxShadow: "0 0 6px var(--green)",
                      display: "inline-block",
                    }}
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Pending workflow actions */}
      {pendingActions > 0 && (
        <div style={{ marginTop: 24 }}>
          <div className="section-header">
            <h2>Pending Workflow Actions</h2>
            <Link href="/workflows">Review all ({pendingActions}) →</Link>
          </div>
          <div className="card" style={{ background: "rgba(245,200,66,0.03)", borderColor: "rgba(245,200,66,0.15)" }}>
            <p style={{ fontSize: 13, color: "var(--text-secondary)" }}>
              <span style={{ color: "var(--yellow)", fontWeight: 700 }}>{pendingActions} action items</span> extracted from recent workflow runs are waiting for your review.
            </p>
            <Link href="/workflows" className="btn" style={{ marginTop: 10, display: "inline-flex" }}>
              Review & Approve →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
