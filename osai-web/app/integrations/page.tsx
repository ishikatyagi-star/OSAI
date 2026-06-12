"use client";

import { useEffect, useMemo, useState } from "react";
import { getIntegrations, getSyncRuns, triggerSync } from "@/lib/api";
import { DEMO_INTEGRATIONS, DEMO_STATS, DEMO_SYNC_RUNS } from "@/lib/demo-data";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { Integration, SyncRun } from "@/lib/types";
import { ConnectorManager } from "@/components/integrations/connector-manager";

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
    state === "connected" ? "#22c55e" : state === "error" ? "#ff5577" : "var(--text-muted)";
  return (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: color,
        boxShadow: state === "connected" ? `0 0 6px ${color}` : "none",
        flexShrink: 0,
      }}
    />
  );
}

export default function IntegrationsPage() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [syncing, setSyncing] = useState<Record<string, boolean>>({});
  const [syncMsg, setSyncMsg] = useState<Record<string, string>>({});
  const [syncRuns, setSyncRuns] = useState<SyncRun[]>([]);
  const [managedKey, setManagedKey] = useState<string | null>(null);

  useEffect(() => {
    getIntegrations().then((data) => {
      const hasConnected = data.some((i) => i.auth_state === "connected");
      setIntegrations(hasConnected ? data : DEMO_INTEGRATIONS);
    });
    getSyncRuns().then((runs) => {
      setSyncRuns(runs.length ? runs : DEMO_SYNC_RUNS);
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

  const display = integrations.length ? integrations : DEMO_INTEGRATIONS;
  const managed = display.find((i) => i.key === managedKey) ?? null;
  const managedRuns = useMemo(
    () =>
      managedKey
        ? syncRuns.filter((r) => r.connector_key === managedKey)
        : [],
    [syncRuns, managedKey]
  );

  return (
    <div>
      <div style={{ marginBottom: 36 }}>
        <h1>Integrations</h1>
        <p className="page-subtitle">
          Connect your company tools to start indexing context. Each connector syncs documents
          into the OSAI knowledge base for search and workflow extraction.
        </p>

        {/* Summary strip */}
        <div className="integration-summary-strip">
          <div className="integration-summary-item">
            <span className="integration-summary-value">
              {display.filter((i) => i.auth_state === "connected").length}
            </span>
            <span className="integration-summary-label">Connected</span>
          </div>
          <div className="integration-summary-divider" />
          <div className="integration-summary-item">
            <span className="integration-summary-value">
              {Object.values(DEMO_STATS.docsPerConnector).reduce((a, b) => a + b, 0).toLocaleString()}
            </span>
            <span className="integration-summary-label">Documents Indexed</span>
          </div>
          <div className="integration-summary-divider" />
          <div className="integration-summary-item">
            <span className="integration-summary-value">
              {display.filter((i) => i.last_sync).length}
            </span>
            <span className="integration-summary-label">Recently Synced</span>
          </div>
        </div>
      </div>

      <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}>
        {display.map((item) => {
          const meta = CONNECTOR_META[item.key] ?? {
            label: item.display_name,
            icon: "⚙",
            color: "var(--text-secondary)",
            description: "",
          };
          const docCount = DEMO_STATS.docsPerConnector[item.key] ?? 0;

          return (
            <div className="card connector-card" key={item.key}>
              {/* Header */}
              <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 16 }}>
                <div
                  className="connector-icon-badge"
                  style={{ background: `${meta.color}18`, color: meta.color }}
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
                  <span className="connector-stat-value" style={{ color: meta.color }}>
                    {docCount > 0 ? docCount.toLocaleString() : "—"}
                  </span>
                  <span className="connector-stat-label">Docs indexed</span>
                </div>
                <div className="connector-stat">
                  <span className="connector-stat-value">
                    {item.capabilities?.length ?? 0}
                  </span>
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
                    style={{
                      padding: "8px 18px",
                      fontSize: 12,
                      background: `${meta.color}18`,
                      border: `1px solid ${meta.color}30`,
                      color: meta.color,
                    }}
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
          { key: "linear", label: "Linear", icon: "📐", color: "#6a4cf5" },
          { key: "confluence", label: "Confluence", icon: "📚", color: "#0099ff" },
        ].map((c) => (
          <div key={c.key} className="card connector-card" style={{ opacity: 0.5 }}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 16 }}>
              <div
                className="connector-icon-badge"
                style={{ background: `${c.color}18`, color: c.color }}
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
    </div>
  );
}
