"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { RotateCw } from "lucide-react";
import { DEMO_WORKFLOW_RUNS, DEMO_STATS, DEMO_DECISIONS } from "@/lib/demo-data";
import { getDashboardMetrics } from "@/lib/api";
import { isDemo } from "@/lib/demo";
import { CONNECTOR_META, getConnectorIcon } from "@/lib/connector-meta";
import { StatusDot } from "@/components/ui/status-dot";

export default function DashboardPage() {
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

  const pendingDecisions = demo
    ? DEMO_DECISIONS.filter((d) => d.status === "proposed").length
    : 0;
  // Real indexed-document count so the dashboard matches Analytics/Sync Runs
  // instead of always reading 0 for signed-in (non-demo) users.
  const [liveDocs, setLiveDocs] = useState<number | null>(null);
  const [liveByConnector, setLiveByConnector] = useState<Record<string, number>>({});
  const [metricsLoading, setMetricsLoading] = useState(!demo);
  const [metricsError, setMetricsError] = useState("");
  const loadMetrics = useCallback(async () => {
    if (demo) {
      setMetricsLoading(false);
      setMetricsError("");
      return;
    }
    setMetricsLoading(true);
    setMetricsError("");
    try {
      const metrics = await getDashboardMetrics(true);
      setLiveDocs(metrics.total_documents);
      setLiveByConnector(metrics.documents_by_connector ?? {});
    } catch {
      setMetricsError("Dashboard metrics could not be loaded. Previous values, if any, have been kept.");
    } finally {
      setMetricsLoading(false);
    }
  }, [demo]);
  useEffect(() => {
    void loadMetrics();
  }, [loadMetrics]);
  const documentsIndexed = demo ? DEMO_STATS.documentsIndexed : (liveDocs ?? 0);
  const dashboardReady = demo || liveDocs !== null;
  const recentDecisions = demo ? DEMO_DECISIONS.slice(0, 4) : [];
  const connectorHealth = demo
    ? [
        { key: "notion", icon: getConnectorIcon("notion"), label: "Notion", docs: 847, status: "connected" },
        { key: "slack", icon: getConnectorIcon("slack"), label: "Slack", docs: 302, status: "connected" },
        { key: "google_drive", icon: getConnectorIcon("google_drive"), label: "Google Drive", docs: 98, status: "connected" },
        { key: "freshdesk", icon: getConnectorIcon("freshdesk"), label: "Freshdesk", docs: 47, status: "connected" },
        { key: "zoom", icon: getConnectorIcon("zoom"), label: "Zoom", docs: 12, status: "connected" },
      ]
    : Object.entries(liveByConnector)
        .filter(([, docs]) => docs > 0)
        .map(([key, docs]) => ({
          key,
          icon: getConnectorIcon(key),
          label: CONNECTOR_META[key]?.label ?? key,
          docs,
          status: "connected",
        }));

  return (
    <div className="dashboard-root">
      <div className="page-header">
        <div className="page-header-left">
          <h1>Dashboard</h1>
          <p>{greeting} - here&apos;s what needs your attention today.</p>
        </div>
        <Link href="/integrations" className="btn btn-primary">
          + Add Context
        </Link>
      </div>

      {!dashboardReady ? (
        <div className="card async-state" role={metricsError ? "alert" : "status"} aria-live="polite">
          {metricsError ? (
            <div>
              <p className="error-text" style={{ marginBottom: 12 }}>{metricsError}</p>
              <button type="button" className="btn btn-primary" onClick={loadMetrics} disabled={metricsLoading}>
                Retry
              </button>
            </div>
          ) : (
            <>
              <RotateCw className="size-5 animate-spin" aria-hidden="true" />
              <p className="meta">Loading workspace metrics...</p>
            </>
          )}
        </div>
      ) : (
        <>
      {metricsError && (
        <div className="card" role="status" aria-live="polite" style={{ marginBottom: 16, padding: "10px 14px" }}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="error-text">{metricsError}</p>
            <button type="button" className="btn" onClick={loadMetrics} disabled={metricsLoading}>
              {metricsLoading ? "Retrying..." : "Retry"}
            </button>
          </div>
        </div>
      )}

      {/* Spotlight banner - violet gradient atmosphere tile */}
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
          <h2 className="text-[30px] font-semibold leading-[1.05] tracking-[-1.4px]" style={{ margin: 0 }}>
            Your company context, working for you.
          </h2>
          <p className="text-body" style={{ marginTop: 10, maxWidth: 480 }}>
            {documentsIndexed > 0
              ? `${documentsIndexed.toLocaleString()} sources indexed across every connector - ask anything, surface blockers, and keep decisions moving.`
              : "Connect your tools to index your company context - then ask anything, surface blockers, and keep decisions moving."}
          </p>
        </div>
        <Link
          href="/ask"
          className="btn btn-primary"
          style={{ flexShrink: 0 }}
        >
          Ask Sheldon →
        </Link>
      </div>

      {/* Stat cards */}
      <div className="stats-grid">
        {[
          { label: "Sources Indexed", value: documentsIndexed, color: "var(--teal)", link: "/analytics" },
          { label: "Pending Decisions", value: pendingDecisions, color: "var(--text-primary)", link: "/decisions" },
          { label: "Pending Actions", value: pendingActions, color: "var(--text-primary)", link: "/automations" },
          { label: "Active Connectors", value: connectorHealth.length, color: "var(--text-primary)", link: "/integrations" },
        ].map((s) => (
          <Link key={s.label} href={s.link} className="stat-card" style={{ textDecoration: "none" }}>
            <div className="stat-card-label">{s.label}</div>
            <div className="stat-card-value" style={{ color: s.color }}>{s.value.toLocaleString()}</div>
          </Link>
        ))}
      </div>

      {/* Two-column layout */}
      <div className="dashboard-two-col" style={{ gap: 24 }}>
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
                    <p className="text-micro font-semibold" style={{ color: "var(--text-primary)", marginBottom: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
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
              {connectorHealth.map((c, i) => {
                const Icon = c.icon;
                return (
                <div
                  key={c.key}
                  className="activity-row"
                  style={{ padding: "10px 16px", borderBottom: i < connectorHealth.length - 1 ? "1px solid var(--border)" : "none" }}
                >
                  <span className="connector-inline-icon" aria-hidden>
                    <Icon size={15} strokeWidth={1.8} />
                  </span>
                  <div style={{ flex: 1 }}>
                    <p className="text-micro font-semibold" style={{ color: "var(--text-primary)", margin: 0 }}>{c.label}</p>
                    <p className="meta">{c.docs.toLocaleString()} docs indexed</p>
                  </div>
                  <StatusDot state={c.status} />
                </div>
              )})}
            </div>
          </div>
      </div>

      {/* Pending workflow actions */}
      {pendingActions > 0 && (
        <div style={{ marginTop: 24 }}>
          <div className="section-header">
            <h2>Pending Workflow Actions</h2>
            <Link href="/automations">Review all ({pendingActions}) →</Link>
          </div>
          <div className="card" style={{ background: "var(--accent-dim)", borderColor: "rgba(41,37,36,0.18)" }}>
            <p className="text-caption" style={{ color: "var(--text-primary)", fontWeight: 400 }}>
              <span className="font-bold" style={{ color: "var(--text-primary)" }}>{pendingActions} action items</span> extracted from recent workflow runs are waiting for your review.
            </p>
            <Link href="/automations" className="btn" style={{ marginTop: 10, display: "inline-flex" }}>
              Review & Approve →
            </Link>
          </div>
        </div>
      )}
        </>
      )}
    </div>
  );
}
