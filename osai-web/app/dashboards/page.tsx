"use client";

import { useCallback, useEffect, useState } from "react";
import { RotateCw } from "lucide-react";
import { getDashboardMetrics, type DashboardMetrics } from "@/lib/api";
import { isDemo } from "@/lib/demo";
import { CONNECTOR_META } from "@/lib/connector-meta";

const TIER_COLOR: Record<string, string> = {
  normal: "var(--green)",
  amber: "var(--orange)",
  red: "var(--red)",
};

const DEMO_METRICS: DashboardMetrics = {
  total_documents: 312,
  documents_by_connector: { notion: 84, google_drive: 142, slack: 63, freshdesk: 23 },
  documents_by_tier: { normal: 240, amber: 56, red: 16 },
  connectors_connected: 3,
  sync_runs_total: 28,
  sync_runs_succeeded: 26,
  last_sync_at: new Date(Date.now() - 3600_000).toISOString(),
  members: 5,
  departments: 5,
  automations: 3,
};

function timeAgo(iso: string | null) {
  if (!iso) return "never";
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

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

export default function DashboardsPage() {
  const [m, setM] = useState<DashboardMetrics | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await getDashboardMetrics();
    setM(res.total_documents === 0 && isDemo() ? DEMO_METRICS : res);
    setLoading(false);
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
        { label: "Sync success", value: successRate === null ? "—" : `${successRate}%`, color: "var(--text-primary)" },
        { label: "Team members", value: m.members, color: "var(--text-primary)" },
        { label: "Departments", value: m.departments, color: "var(--text-primary)" },
        { label: "Automations", value: m.automations, color: "var(--text-primary)" },
      ]
    : [];

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Dashboards</h1>
          <p>Live metrics aggregated from your connected data sources and workspace.</p>
        </div>
        <button className="btn" onClick={load} style={{ display: "inline-flex" }}>
          <RotateCw className="size-3.5" /> Refresh
        </button>
      </div>

      {loading && !m ? (
        <div className="card" style={{ textAlign: "center", padding: "44px 24px" }}>
          <p className="meta">Loading metrics…</p>
        </div>
      ) : (
        <>
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
