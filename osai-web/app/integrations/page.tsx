"use client";

import { useEffect, useMemo, useState } from "react";
import { getIntegrations, getSyncRuns, triggerSync } from "@/lib/api";
import { DEMO_INTEGRATIONS, DEMO_STATS, DEMO_SYNC_RUNS } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { Integration, SyncRun } from "@/lib/types";
import { ConnectorManager } from "@/components/integrations/connector-manager";
import { DataRoutingPanel } from "@/components/integrations/data-routing-panel";

type Tab = "connectors" | "routing";

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function StatusDot({ state }: { state: string }) {
  const color =
    state === "connected" ? "var(--green)" : state === "error" ? "var(--red)" : "var(--text-muted)";
  return (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: color,
        boxShadow: state === "connected" ? "0 0 6px var(--green)" : "none",
        flexShrink: 0,
      }}
    />
  );
}

export default function IntegrationsPage() {
  const [tab, setTab] = useState<Tab>("connectors");
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [syncing, setSyncing] = useState<Record<string, boolean>>({});
  const [syncMsg, setSyncMsg] = useState<Record<string, string>>({});
  const [syncRuns, setSyncRuns] = useState<SyncRun[]>([]);
  const [managedKey, setManagedKey] = useState<string | null>(null);

  // Honour ?tab=routing (e.g. from the Settings hub / old data-routing route).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("tab") === "routing") setTab("routing");
  }, []);

  useEffect(() => {
    getIntegrations().then((data) => {
      const hasConnected = data.some((i) => i.auth_state === "connected");
      // Show real connectors; only substitute the demo set in demo mode.
      setIntegrations(!hasConnected && isDemo() && !data.length ? DEMO_INTEGRATIONS : data);
    });
    getSyncRuns().then((runs) => {
      setSyncRuns(runs.length ? runs : isDemo() ? DEMO_SYNC_RUNS : []);
    });
  }, []);

  async function handleSync(key: string) {
    setSyncing((s) => ({ ...s, [key]: true }));
    setSyncMsg((m) => ({ ...m, [key]: "" }));
    try {
      await triggerSync(key);
      setSyncMsg((m) => ({ ...m, [key]: "Sync started" }));
    } catch {
      setSyncMsg((m) => ({ ...m, [key]: "Sync triggered (demo mode)" }));
    } finally {
      setSyncing((s) => ({ ...s, [key]: false }));
      setTimeout(() => setSyncMsg((m) => ({ ...m, [key]: "" })), 3000);
    }
  }

  function handleToggleConnection(key: string, connect: boolean) {
    setIntegrations((prev) =>
      prev.map((i) =>
        i.key === key
          ? {
              ...i,
              auth_state: connect ? "connected" : "not_configured",
              sync_error: null,
              last_sync: connect ? i.last_sync : null,
            }
          : i
      )
    );
  }

  const demo = isDemo();
  const display = integrations.length ? integrations : demo ? DEMO_INTEGRATIONS : [];
  const managed = display.find((i) => i.key === managedKey) ?? null;
  const managedRuns = useMemo(
    () => (managedKey ? syncRuns.filter((r) => r.connector_key === managedKey) : []),
    [syncRuns, managedKey]
  );

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Integrations</h1>
          <p>
            Connect your company tools to start indexing context, and control how the information
            inside them is classified into data tiers.
          </p>
        </div>
      </div>

      {/* Tabs: Connectors | Data Routing */}
      <div style={{ display: "flex", gap: 8, marginBottom: 22, borderBottom: "1px solid var(--border)" }}>
        {([
          { key: "connectors", label: "Connectors" },
          { key: "routing", label: "Data Routing" },
        ] as const).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              background: "none",
              border: "none",
              borderBottom: tab === t.key ? "2px solid var(--accent)" : "2px solid transparent",
              color: tab === t.key ? "var(--text-primary)" : "var(--text-muted)",
              fontSize: 13,
              fontWeight: 600,
              padding: "8px 4px",
              marginBottom: -1,
              cursor: "pointer",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "routing" ? (
        <DataRoutingPanel />
      ) : (
        <>
          {/* Summary — dashboard stat-card styling */}
          <div className="stats-grid stats-grid--auto">
            <div className="stat-card">
              <div className="stat-card-label">Connected</div>
              <div className="stat-card-value">
                {display.filter((i) => i.auth_state === "connected").length}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-card-label">Documents Indexed</div>
              <div className="stat-card-value">
                {demo
                  ? Object.values(DEMO_STATS.docsPerConnector).reduce((a, b) => a + b, 0).toLocaleString()
                  : "—"}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-card-label">Synced (last 24h)</div>
              <div className="stat-card-value">
                {display.filter((i) => {
                  if (!i.last_sync) return false;
                  return Date.now() - new Date(i.last_sync).getTime() < 24 * 60 * 60 * 1000;
                }).length}
              </div>
            </div>
          </div>

          {display.length === 0 && (
            <div className="card" style={{ textAlign: "center", padding: "44px 24px", marginBottom: 16 }}>
              <p style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>No connectors yet</p>
              <p className="meta" style={{ maxWidth: 420, margin: "0 auto" }}>
                The backend didn&apos;t return any connectors. Once available, connect Notion, Google
                Drive, Slack and more to start indexing your context.
              </p>
            </div>
          )}

          <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}>
            {display.map((item) => {
              const meta = CONNECTOR_META[item.key] ?? {
                label: item.display_name,
                icon: "⚙",
                color: "var(--text-secondary)",
                description: "",
              };
              const docCount = demo ? DEMO_STATS.docsPerConnector[item.key] ?? 0 : 0;

              return (
                <div className="card connector-card" key={item.key}>
                  {/* Header */}
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 16 }}>
                    <div
                      className="connector-icon-badge"
                      style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
                    >
                      {meta.icon}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                        <h2 style={{ margin: 0, fontSize: 16 }}>{meta.label}</h2>
                        <StatusDot state={item.auth_state} />
                        <span
                          className={`badge badge-${item.auth_state === "connected" ? "green" : item.auth_state === "error" ? "red" : "grey"}`}
                        >
                          {item.auth_state === "not_configured" ? "not connected" : item.auth_state}
                        </span>
                      </div>
                      <p className="meta" style={{ margin: 0, fontSize: 12, lineHeight: 1.4 }}>
                        {meta.description}
                      </p>
                    </div>
                  </div>

                  {/* Stats row */}
                  <div className="connector-stats-row">
                    <div className="connector-stat">
                      <span className="connector-stat-value">
                        {docCount > 0 ? docCount.toLocaleString() : "—"}
                      </span>
                      <span className="connector-stat-label">Docs indexed</span>
                    </div>
                    <div className="connector-stat">
                      <span className="connector-stat-value">{item.capabilities?.length ?? 0}</span>
                      <span className="connector-stat-label">Capabilities</span>
                    </div>
                    <div className="connector-stat">
                      <span className="connector-stat-value">
                        {item.last_sync ? timeAgo(item.last_sync) : "—"}
                      </span>
                      <span className="connector-stat-label">Last sync</span>
                    </div>
                  </div>

                  {/* Capabilities */}
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
                    {(item.capabilities ?? []).map((cap) => (
                      <span key={cap} className="badge badge-grey" style={{ fontSize: 10 }}>
                        {cap}
                      </span>
                    ))}
                  </div>

                  {item.sync_error && (
                    <p className="error-text" style={{ fontSize: 12, marginBottom: 12 }}>
                      ⚠ {item.sync_error}
                    </p>
                  )}

                  {/* Actions */}
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4 }}>
                    {item.auth_state === "connected" ? (
                      <button
                        className="btn btn-primary"
                        style={{ padding: "8px 18px", fontSize: 12 }}
                        disabled={syncing[item.key]}
                        onClick={() => handleSync(item.key)}
                      >
                        {syncing[item.key] ? "Syncing…" : "Sync now"}
                      </button>
                    ) : (
                      <button
                        className="btn"
                        style={{ padding: "8px 18px", fontSize: 12 }}
                        onClick={() => setManagedKey(item.key)}
                      >
                        Connect
                      </button>
                    )}
                    <button
                      className="btn"
                      style={{ padding: "8px 16px", fontSize: 12 }}
                      onClick={() => setManagedKey(item.key)}
                    >
                      Manage
                    </button>
                    {syncMsg[item.key] && (
                      <span className="success-text" style={{ fontSize: 12 }}>
                        ✓ {syncMsg[item.key]}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}

            {/* Coming-soon connectors */}
            {[
              { key: "linear", label: "Linear", icon: "📐" },
              { key: "confluence", label: "Confluence", icon: "📚" },
            ].map((c) => (
              <div key={c.key} className="card connector-card" style={{ opacity: 0.5 }}>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 16 }}>
                  <div
                    className="connector-icon-badge"
                    style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
                  >
                    {c.icon}
                  </div>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                      <h2 style={{ margin: 0, fontSize: 16 }}>{c.label}</h2>
                      <span className="badge badge-grey" style={{ fontSize: 10 }}>coming soon</span>
                    </div>
                    <p className="meta" style={{ margin: 0, fontSize: 12 }}>
                      {CONNECTOR_META[c.key]?.description}
                    </p>
                  </div>
                </div>
                <button className="btn" style={{ padding: "8px 18px", fontSize: 12, opacity: 0.5 }} disabled>
                  Notify me
                </button>
              </div>
            ))}
          </div>

          <ConnectorManager
            integration={managed}
            open={managedKey !== null}
            onOpenChange={(o) => setManagedKey(o ? managedKey : null)}
            recentRuns={managedRuns}
            syncing={managedKey ? !!syncing[managedKey] : false}
            onSync={handleSync}
            onToggleConnection={handleToggleConnection}
          />
        </>
      )}
    </div>
  );
}
