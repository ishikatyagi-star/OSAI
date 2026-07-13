"use client";

import { useCallback, useEffect, useState } from "react";
import { RotateCw } from "lucide-react";
import { getDashboardMetrics, type DashboardMetrics } from "@/lib/api";
import { isDemo } from "@/lib/demo";
import { CONNECTOR_META } from "@/lib/connector-meta";
import {
  DEMO_DEPARTMENTS,
  DEMO_INTEGRATIONS,
  DEMO_STATS,
  DEMO_SYNC_RUNS,
  DEMO_TEAM_MEMBERS,
} from "@/lib/demo-data";
import { timeAgo } from "@/lib/utils";

const TIER_COLOR: Record<string, string> = {
  normal: "var(--green)",
  amber: "var(--orange)",
  red: "var(--red)",
};

const DEMO_METRICS: DashboardMetrics = {
  total_documents: DEMO_STATS.documentsIndexed,
  documents_by_connector: DEMO_STATS.docsPerConnector,
  documents_by_tier: { normal: 1024, amber: 230, red: 52 },
  connectors_connected: DEMO_INTEGRATIONS.filter((item) => item.auth_state === "connected").length,
  sync_runs_total: DEMO_SYNC_RUNS.length,
  sync_runs_succeeded: DEMO_SYNC_RUNS.filter((run) => run.status === "succeeded").length,
  last_sync_at: DEMO_SYNC_RUNS.map((run) => run.started_at).sort().at(-1) ?? null,
  members: DEMO_TEAM_MEMBERS.length,
  departments: DEMO_DEPARTMENTS.length,
  automations: 3,
};


function BarChart({ data, colorFor }: { data: Record<string, number>; colorFor: (k: string) => string }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  if (entries.length === 0) {
    return <p className="meta">No data yet.</p>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {entries.map(([key, value]) => (
        <div key={key} style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ width: 120, fontSize: 12, color: "var(--text-secondary)", textTransform: "capitalize" }}>
            {CONNECTOR_META[key]?.label ?? key.replace(/_/g, " ")}
          </span>
          <div style={{ flex: 1, height: 18, background: "var(--bg-elevated)", borderRadius: 6, overflow: "hidden" }}>
            <div
              style={{
                width: `${(value / max) * 100}%`,
                height: "100%",
                background: colorFor(key),
                borderRadius: 6,
                transition: "width .3s",
              }}
            />
          </div>
          <span style={{ width: 44, textAlign: "right", fontSize: 12, fontWeight: 600, fontFamily: "var(--font-mono)" }}>
            {value.toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function AnalyticsPage() {
  const [m, setM] = useState<DashboardMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    if (isDemo()) {
      setM(DEMO_METRICS);
      setLoading(false);
      return;
    }
    try {
      setM(await getDashboardMetrics(true));
    } catch {
      setError("Metrics could not be loaded. The previous values, if any, have been kept.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const successRate =
    m && m.sync_runs_total > 0 ? Math.round((m.sync_runs_succeeded / m.sync_runs_total) * 100) : null;

  const STATS = m
    ? [
        { label: "Documents indexed", value: m.total_documents, color: "var(--teal)" },
        { label: "Connected tools", value: m.connectors_connected, color: "var(--green)" },
        { label: "Sync success", value: successRate === null ? "-" : `${successRate}%`, color: "var(--text-primary)" },
        { label: "Team members", value: m.members, color: "var(--text-primary)" },
        { label: "Departments", value: m.departments, color: "var(--text-primary)" },
        { label: "Automations", value: m.automations, color: "var(--text-primary)" },
      ]
    : [];

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Analytics</h1>
          <p>Live metrics aggregated from your connected data sources and workspace.</p>
        </div>
        <button
          type="button"
          className="btn"
          onClick={load}
          style={{ display: "inline-flex" }}
          disabled={loading}
          aria-busy={loading}
        >
          <RotateCw className={`size-3.5${loading ? " animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {error && !m ? (
        <div className="card async-state" role="alert">
          <div>
            <p className="error-text" style={{ marginBottom: 12 }}>{error}</p>
            <button type="button" className="btn btn-primary" onClick={load}>Retry</button>
          </div>
        </div>
      ) : loading && !m ? (
        <div className="card async-state" role="status" aria-live="polite">
          <RotateCw className="size-5 animate-spin" aria-hidden="true" />
          <p className="meta">Loading metrics…</p>
        </div>
      ) : (
        <>
          {error && m && (
            <div className="card" role="status" aria-live="polite" style={{ marginBottom: 16, padding: "10px 14px" }}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="error-text">{error}</p>
                <button type="button" className="btn" onClick={load} disabled={loading}>
                  {loading ? "Retrying..." : "Retry"}
                </button>
              </div>
            </div>
          )}
          <div className="stats-grid stats-grid--auto" style={{ marginBottom: 24 }}>
            {STATS.map((s) => (
              <div key={s.label} className="stat-card">
                <div className="stat-card-label">{s.label}</div>
                <div className="stat-card-value" style={{ color: s.color }}>
                  {typeof s.value === "number" ? s.value.toLocaleString() : s.value}
                </div>
              </div>
            ))}
          </div>

          <div className="dashboard-two-col" style={{ gap: 24 }}>
            <div className="card">
              <div className="section-header" style={{ marginBottom: 16 }}>
                <h2>Documents by source</h2>
              </div>
              <BarChart
                data={m?.documents_by_connector ?? {}}
                colorFor={() => "var(--accent)"}
              />
            </div>
            <div className="card">
              <div className="section-header" style={{ marginBottom: 16 }}>
                <h2>Documents by sensitivity tier</h2>
              </div>
              <BarChart
                data={m?.documents_by_tier ?? {}}
                colorFor={(k) => TIER_COLOR[k] ?? "var(--text-muted)"}
              />
            </div>
          </div>

          <p className="meta" style={{ marginTop: 16, fontSize: 11 }}>
            Last sync {timeAgo(m?.last_sync_at ?? null)} · {m?.sync_runs_total ?? 0} total sync runs.
          </p>
        </>
      )}
    </div>
  );
}
