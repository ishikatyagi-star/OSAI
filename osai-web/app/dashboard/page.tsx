"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { User } from "lucide-react";
import { DEMO_WORKFLOW_RUNS, DEMO_STATS, DEMO_DECISIONS } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import { StatusDot } from "@/components/ui/status-dot";

const DEMO_ATTENTION_ITEMS = [
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

  // Time-of-day greeting, resolved on the client to match the viewer's clock
  // (avoids a server/client hydration mismatch).
  const [greeting, setGreeting] = useState("Welcome");
  useEffect(() => {
    const h = new Date().getHours();
    setGreeting(h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening");
  }, []);

  const demo = isDemo();

  const pendingActions = demo
    ? DEMO_WORKFLOW_RUNS.flatMap((r) => r.action_items ?? []).filter(
        (a) => a.status === "needs_review"
      ).length
    : 0;

  const attentionItems = demo ? DEMO_ATTENTION_ITEMS : [];
  const active = attentionItems.filter(
    (i) => !dismissed.has(i.id) && !snoozed.has(i.id)
  );

  const pendingDecisions = demo
    ? DEMO_DECISIONS.filter((d) => d.status === "proposed").length
    : 0;
  const documentsIndexed = demo ? DEMO_STATS.documentsIndexed : 0;
  const recentDecisions = demo ? DEMO_DECISIONS.slice(0, 4) : [];
  const connectorHealth = demo
    ? [
        { key: "notion", icon: "📝", label: "Notion", docs: 847, status: "connected" },
        { key: "slack", icon: "💬", label: "Slack", docs: 302, status: "connected" },
        { key: "google_drive", icon: "📁", label: "Google Drive", docs: 98, status: "connected" },
        { key: "freshdesk", icon: "🎫", label: "Freshdesk", docs: 47, status: "connected" },
        { key: "zoom", icon: "📹", label: "Zoom", docs: 12, status: "connected" },
      ]
    : [];

  return (
    <div className="dashboard-root">
      <div className="page-header">
        <div className="page-header-left">
          <h1>Dashboard</h1>
          <p>{greeting} — here&apos;s what needs your attention today.</p>
        </div>
        <Link href="/inbox" className="btn btn-primary">
          + Add Context
        </Link>
      </div>

      {/* Spotlight banner — violet gradient atmosphere tile */}
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
          <div className="spotlight-eyebrow">
            Company pulse
          </div>
          <h2 style={{ fontSize: 30, lineHeight: 1.05, letterSpacing: "-1.4px", margin: 0 }}>
            Your company context, working for you.
          </h2>
          <p className="text-body" style={{ marginTop: 10, maxWidth: 480 }}>
            {documentsIndexed > 0
              ? `${documentsIndexed.toLocaleString()} sources indexed across every connector — ask anything, surface blockers, and keep decisions moving.`
              : "Connect your tools to index your company context — then ask anything, surface blockers, and keep decisions moving."}
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
          { label: "Pending Decisions", value: pendingDecisions, color: "var(--text-primary)", link: "/decisions" },
          { label: "Overdue Follow-ups", value: active.filter(i => i.tag === "follow-up").length, color: "var(--text-primary)", link: "/decisions?source=osai" },
          { label: "Context This Week", value: documentsIndexed, color: "var(--teal)", link: "/inbox" },
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
              <p className="text-caption" style={{ color: "var(--green)", fontWeight: 600 }}>All clear!</p>
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
                <span><User size={12} style={{ display: "inline", verticalAlign: "middle", marginRight: 3 }} />{item.owner}</span>
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
              {recentDecisions.length === 0 && (
                <div style={{ padding: "20px 16px", textAlign: "center" }}>
                  <p className="meta">No decisions logged yet.</p>
                </div>
              )}
              {recentDecisions.map((d, i) => (
                <div
                  key={d.id}
                  className="activity-row"
                  style={{
                    padding: "12px 16px",
                    borderBottom: i < 3 ? "1px solid var(--border)" : "none",
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p className="text-micro" style={{ fontWeight: 600, color: "var(--text-primary)", marginBottom: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
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
              {connectorHealth.length === 0 && (
                <div style={{ padding: "20px 16px", textAlign: "center" }}>
                  <p className="meta" style={{ marginBottom: 10 }}>No connectors syncing yet.</p>
                  <Link href="/integrations" className="btn" style={{ display: "inline-flex" }}>
                    Connect tools →
                  </Link>
                </div>
              )}
              {connectorHealth.map((c, i) => (
                <div
                  key={c.key}
                  className="activity-row"
                  style={{ padding: "10px 16px", borderBottom: i < connectorHealth.length - 1 ? "1px solid var(--border)" : "none" }}
                >
                  <span style={{ fontSize: 15 }}>{c.icon}</span>
                  <div style={{ flex: 1 }}>
                    <p className="text-micro" style={{ fontWeight: 600, color: "var(--text-primary)", margin: 0 }}>{c.label}</p>
                    <p className="meta">{c.docs.toLocaleString()} docs indexed</p>
                  </div>
                  <StatusDot state={c.status} />
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
          <div className="card" style={{ background: "var(--accent-dim)", borderColor: "rgba(0,153,255,0.18)" }}>
            <p className="text-caption" style={{ color: "var(--text-secondary)", fontWeight: 400 }}>
              <span style={{ color: "var(--accent)", fontWeight: 700 }}>{pendingActions} action items</span> extracted from recent workflow runs are waiting for your review.
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
