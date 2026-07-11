"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Check, Plus } from "lucide-react";
import { COMPOSIO_TOOLKIT, composioConnect, composioDisconnect, getDashboardMetrics, getIntegrations, getSyncRuns, triggerSync } from "@/lib/api";
import { DEMO_INTEGRATIONS, DEMO_STATS, DEMO_SYNC_RUNS } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import { CONNECTOR_META, getConnectorIcon } from "@/lib/connector-meta";
import type { Integration, SyncRun } from "@/lib/types";
import { AddConnectorDialog } from "@/components/integrations/add-connector-dialog";
import { ConnectorManager } from "@/components/integrations/connector-manager";
import { UploadCard } from "@/components/integrations/upload-card";
import { Button } from "@/components/ui/button";
import { DataRoutingPanel } from "@/components/integrations/data-routing-panel";
import { StatusDot } from "@/components/ui/status-dot";
import { TabsPill, TabsPillList, TabsPillTrigger, TabsPillContent } from "@/components/ui/tabs-pill";
import { brandText, timeAgo } from "@/lib/utils";

type Tab = "connectors" | "routing";


export default function IntegrationsPage() {
  const [tab, setTab] = useState<Tab>("connectors");
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [syncing, setSyncing] = useState<Record<string, boolean>>({});
  const [syncMsg, setSyncMsg] = useState<Record<string, string>>({});
  const [syncRuns, setSyncRuns] = useState<SyncRun[]>([]);
  const [managedKey, setManagedKey] = useState<string | null>(null);
  const [justConnected, setJustConnected] = useState(false);
  const [catalogOpen, setCatalogOpen] = useState(false);
  // Real per-connector indexed-doc counts so the cards match Analytics/Sync Runs
  // instead of always showing "-" for signed-in users.
  const [docsByConnector, setDocsByConnector] = useState<Record<string, number>>({});

  function loadIntegrations() {
    getIntegrations().then((data) => {
      const hasConnected = data.some((i) => i.auth_state === "connected");
      // Show real connectors; only substitute the demo set in demo mode.
      setIntegrations(!hasConnected && isDemo() && !data.length ? DEMO_INTEGRATIONS : data);
    });
    if (!isDemo()) {
      getDashboardMetrics().then((m) => setDocsByConnector(m.documents_by_connector ?? {}));
    }
  }

  // Honour ?tab=routing and ?connected=1 (back from the Composio OAuth round-trip).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("tab") === "routing") setTab("routing");
    if (params.get("connected") === "1") {
      setJustConnected(true);
      setTimeout(() => setJustConnected(false), 6000);
      // Clean the query string so a refresh doesn't re-show the banner.
      window.history.replaceState({}, "", "/integrations");
    }
  }, []);

  useEffect(() => {
    loadIntegrations();
    getSyncRuns().then((runs) => {
      setSyncRuns(runs.length ? runs : isDemo() ? DEMO_SYNC_RUNS : []);
    });
  }, []);

  async function handleSync(key: string) {
    setSyncing((s) => ({ ...s, [key]: true }));
    setSyncMsg((m) => ({ ...m, [key]: "" }));
    try {
      const res = (await triggerSync(key)) as {
        documents_indexed?: number;
        status?: string;
        error?: string | null;
      };
      const indexed = Number(res.documents_indexed ?? 0);
      // Composio syncs now run in the background and return "started"; the docs
      // land shortly and show up in Sync Runs, so don't claim a count yet.
      // A 200 response can still carry a failed persisted run (e.g. missing
      // credentials) - report that honestly, never as "Sync complete".
      setSyncMsg((m) => ({
        ...m,
        [key]:
          res.status === "failed"
            ? `Sync failed - ${(res.error || "see Sync Runs for details.").split("\n")[0].slice(0, 140)}`
            : res.status === "started"
              ? "Sync started - files will appear in Sync Runs shortly."
              : indexed > 0
                ? `Indexed ${indexed} file${indexed > 1 ? "s" : ""}`
                : "Sync complete - no new documents.",
      }));
      loadIntegrations();
    } catch {
      setSyncMsg((m) => ({
        ...m,
        [key]: isDemo()
          ? "Sync triggered (demo mode)"
          : "Sync failed - please try again.",
      }));
    } finally {
      setSyncing((s) => ({ ...s, [key]: false }));
      setTimeout(() => setSyncMsg((m) => ({ ...m, [key]: "" })), 6000);
    }
  }

  async function handleConnectStart(key: string) {
    setSyncMsg((m) => ({ ...m, [key]: "Opening authorization…" }));
    try {
      const res = await composioConnect(key);
      if (res.redirect_url) {
        // Full-page navigation to Composio's OAuth consent screen.
        window.location.href = res.redirect_url;
      } else {
        // No redirect URL means the backend couldn't start the handshake -
        // surface it plainly instead of silently doing nothing.
        setSyncMsg((m) => ({
          ...m,
          [key]: res.error || "Couldn't start authorization - please try again.",
        }));
      }
    } catch {
      setSyncMsg((m) => ({
        ...m,
        [key]: "Couldn't reach the server to start authorization. Try again in a moment.",
      }));
    }
  }

  async function handleToggleConnection(key: string, connect: boolean) {
    if (connect) {
      // Real connect = OAuth handshake via Composio (redirects the browser).
      await handleConnectStart(key);
      return;
    }
    // Real disconnect = revoke the Composio connection so a later Connect
    // starts a fresh handshake. Only reflect it in the UI once it succeeds.
    setSyncMsg((m) => ({ ...m, [key]: "Disconnecting…" }));
    try {
      await composioDisconnect(key);
      setIntegrations((prev) =>
        prev.map((i) =>
          i.key === key
            ? { ...i, auth_state: "not_configured", sync_error: null, last_sync: null }
            : i
        )
      );
      setSyncMsg((m) => ({ ...m, [key]: "Disconnected" }));
    } catch {
      setSyncMsg((m) => ({ ...m, [key]: "Couldn't disconnect - try again" }));
    }
  }

  const demo = isDemo();
  const rawDisplay = integrations.length ? integrations : demo ? DEMO_INTEGRATIONS : [];
  // Defensive dedupe so one app never renders as two cards.
  const display = Array.from(
    new Map(rawDisplay.map((i) => [i.key, i])).values()
  );
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
        <Button size="lg" className="min-w-[152px] shadow-sm" onClick={() => setCatalogOpen(true)}>
          <Plus size={14} /> Add connector
        </Button>
      </div>

      <AddConnectorDialog
        open={catalogOpen}
        onOpenChange={setCatalogOpen}
        connectedKeys={integrations
          .filter((i) => i.auth_state === "connected")
          // Catalog entries use Composio slugs; translate native keys so
          // already-connected apps read "Connected" in the dialog.
          .map((i) => COMPOSIO_TOOLKIT[i.key] ?? i.key)}
      />

      {/* Tabs: Connectors | Data Routing */}
      <TabsPill value={tab} onValueChange={(v) => setTab(v as Tab)}>
        <TabsPillList>
          <TabsPillTrigger value="connectors">Connectors</TabsPillTrigger>
          <TabsPillTrigger value="routing">Data Routing</TabsPillTrigger>
        </TabsPillList>

        <TabsPillContent value="routing">
          <DataRoutingPanel />
        </TabsPillContent>

        <TabsPillContent value="connectors">
          {justConnected && (
            <div
              className="card text-caption"
              style={{
                marginBottom: 16,
                borderColor: "var(--green)",
                background: "color-mix(in srgb, var(--green) 10%, transparent)",
                color: "var(--green)",
                padding: "12px 16px",
                fontWeight: 600,
              }}
            >
              <span className="inline-flex items-start gap-1.5">
                <Check className="mt-0.5 size-3.5 shrink-0" strokeWidth={2} />
                <span>Connected. Your data is being indexed - click “Sync now” on the connector to pull it in.</span>
              </span>
            </div>
          )}

          {/* Direct file upload - same ingestion pipeline as connector syncs */}
          <UploadCard onUploaded={loadIntegrations} />

          {/* Summary - dashboard stat-card styling */}
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
                {(demo
                  ? Object.values(DEMO_STATS.docsPerConnector).reduce((a, b) => a + b, 0)
                  : Object.values(docsByConnector).reduce((a, b) => a + b, 0)
                ).toLocaleString()}
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
              <p className="text-body font-semibold" style={{ marginBottom: 6 }}>No connectors yet</p>
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
                color: "var(--text-secondary)",
                description: "",
              };
              const Icon = getConnectorIcon(item.key);
              const docCount = demo
                ? DEMO_STATS.docsPerConnector[item.key] ?? 0
                : docsByConnector[item.key] ?? 0;

              return (
                <div className="card connector-card" key={item.key}>
                  {/* Header */}
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 16 }}>
                    <div
                      className="connector-icon-badge"
                      style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
                    >
                      <Icon size={18} strokeWidth={1.8} />
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                        <h2 style={{ margin: 0 }}>{brandText(meta.label)}</h2>
                        <StatusDot state={item.auth_state} />
                        <span
                          className={`badge badge-${item.auth_state === "connected" ? "green" : item.auth_state === "error" ? "red" : "grey"}`}
                        >
                          {item.auth_state === "not_configured" ? "not connected" : item.auth_state}
                        </span>
                      </div>
                      <p className="meta" style={{ margin: 0 }}>
                        {item.auth_state === "connected" && item.account_email
                          ? `Connected as ${item.account_email}`
                          : brandText(meta.description)}
                      </p>
                    </div>
                  </div>

                  {/* Stats row */}
                  <div className="connector-stats-row">
                    <div className="connector-stat">
                      <span className="connector-stat-value">
                        {docCount > 0 ? docCount.toLocaleString() : "-"}
                      </span>
                      <span className="connector-stat-label">Docs indexed</span>
                    </div>
                    <div className="connector-stat">
                      <span className="connector-stat-value">{item.capabilities?.length ?? 0}</span>
                      <span className="connector-stat-label">Capabilities</span>
                    </div>
                    <div className="connector-stat">
                      <span className="connector-stat-value">
                        {item.last_sync ? timeAgo(item.last_sync) : "-"}
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
                    <p className="error-text" style={{ marginBottom: 12, display: "inline-flex", alignItems: "flex-start", gap: 6 }}>
                      <AlertTriangle className="mt-0.5 size-3.5 shrink-0" strokeWidth={1.8} />
                      <span>{brandText(item.sync_error)}</span>
                    </p>
                  )}

                  {/* Actions */}
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4 }}>
                    {item.auth_state === "connected" ? (
                      <button
                        className="btn btn-primary btn-sm"
                        disabled={syncing[item.key]}
                        onClick={() => handleSync(item.key)}
                      >
                        {syncing[item.key] ? "Syncing…" : "Sync now"}
                      </button>
                    ) : (
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => handleConnectStart(item.key)}
                      >
                        Connect
                      </button>
                    )}
                    <button
                      className="btn btn-sm"
                      onClick={() => setManagedKey(item.key)}
                    >
                      Manage
                    </button>
                    {syncMsg[item.key] &&
                      (/failed/i.test(syncMsg[item.key]) ? (
                        <span className="inline-flex items-center gap-1.5" style={{ color: "var(--red)", fontSize: 12 }}>
                          <AlertTriangle className="size-3.5" strokeWidth={2} />
                          {syncMsg[item.key]}
                        </span>
                      ) : (
                        <span className="success-text inline-flex items-center gap-1.5">
                          <Check className="size-3.5" strokeWidth={2} />
                          {syncMsg[item.key]}
                        </span>
                      ))}
                  </div>
                </div>
              );
            })}

          </div>

          <ConnectorManager
            integration={managed}
            open={managedKey !== null}
            onOpenChange={(o) => setManagedKey(o ? managedKey : null)}
            recentRuns={managedRuns}
            syncing={managedKey ? !!syncing[managedKey] : false}
            syncMessage={managedKey ? syncMsg[managedKey] ?? "" : ""}
            onSync={handleSync}
            onToggleConnection={handleToggleConnection}
          />
        </TabsPillContent>
      </TabsPill>
    </div>
  );
}
