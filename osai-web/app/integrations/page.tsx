"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Check, Info, Loader2, Plus } from "lucide-react";
import { COMPOSIO_TOOLKIT, composioConnect, composioDisconnect, getDashboardMetrics, getIntegrations, getSyncRuns, triggerSync } from "@/lib/api";
import { DEMO_INTEGRATIONS, DEMO_STATS, DEMO_SYNC_RUNS } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import { CONNECTOR_META, getConnectorIcon } from "@/lib/connector-meta";
import type { Integration, SyncRun } from "@/lib/types";
import { AddConnectorDialog } from "@/components/integrations/add-connector-dialog";
import { ConnectorManager } from "@/components/integrations/connector-manager";
import { Button } from "@/components/ui/button";
import { StatusDot } from "@/components/ui/status-dot";
import { brandText, timeAgo } from "@/lib/utils";
import { SheldonMascot } from "@/components/sheldon-mascot";

type ConnectorFeedbackTone = "pending" | "success" | "error" | "info";

function ConnectorFeedback({ message, tone }: { message: string; tone: ConnectorFeedbackTone }) {
  const error = tone === "error";
  const pending = tone === "pending";
  const info = tone === "info";
  return (
    <span
      className="inline-flex items-center gap-1.5"
      role={error ? "alert" : "status"}
      aria-live="polite"
      style={{ color: error ? "var(--red)" : pending || info ? "var(--blue)" : "var(--green)", fontSize: 12 }}
    >
      {error ? (
        <AlertTriangle className="size-3.5" strokeWidth={2} />
      ) : info ? (
        <Info className="size-3.5" strokeWidth={2} />
      ) : pending ? (
        <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
      ) : (
        <Check className="size-3.5" strokeWidth={2} />
      )}
      {message}
    </span>
  );
}



export default function IntegrationsPage() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [syncing, setSyncing] = useState<Record<string, boolean>>({});
  const [connecting, setConnecting] = useState<Record<string, boolean>>({});
  const [syncMsg, setSyncMsg] = useState<Record<string, string>>({});
  const [syncTone, setSyncTone] = useState<Record<string, "pending" | "success" | "error" | "info">>({});
  const [syncRuns, setSyncRuns] = useState<SyncRun[]>([]);
  const [syncRunsLoading, setSyncRunsLoading] = useState(true);
  const [syncRunsError, setSyncRunsError] = useState("");
  const [managedKey, setManagedKey] = useState<string | null>(null);
  const [justConnected, setJustConnected] = useState(false);
  const [catalogOpen, setCatalogOpen] = useState(false);
  // Real per-connector indexed-doc counts so the cards match Analytics/Sync Runs
  // instead of always showing "-" for signed-in users.
  const [docsByConnector, setDocsByConnector] = useState<Record<string, number>>({});
  const [metricsAvailable, setMetricsAvailable] = useState(true);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  async function loadIntegrations() {
    setLoading(true);
    setLoadError("");
    if (isDemo()) {
      setIntegrations(DEMO_INTEGRATIONS);
      setDocsByConnector(DEMO_STATS.docsPerConnector);
      setLoading(false);
      return;
    }
    try {
      const [integrationResult, metricsResult] = await Promise.allSettled([
        getIntegrations(true),
        getDashboardMetrics(true),
      ]);
      if (integrationResult.status === "rejected") throw integrationResult.reason;
      setIntegrations(integrationResult.value);
      if (metricsResult.status === "fulfilled") {
        setDocsByConnector(metricsResult.value.documents_by_connector ?? {});
        setMetricsAvailable(true);
      } else {
        setDocsByConnector({});
        setMetricsAvailable(false);
      }
    } catch {
      setLoadError("Integrations could not be loaded. Check your connection and retry.");
    } finally {
      setLoading(false);
    }
  }

  // Honour ?connected=1 (back from the Composio OAuth round-trip) and ?catalog=1
  // (arriving from onboarding - open the full 1,000+ connector catalog directly).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("connected") === "1") {
      setJustConnected(true);
      setTimeout(() => setJustConnected(false), 6000);
    }
    if (params.get("catalog") === "1" && !isDemo()) {
      setCatalogOpen(true);
    }
    if (params.get("connected") === "1" || params.get("catalog") === "1") {
      // Clean the query string so a refresh doesn't re-trigger.
      window.history.replaceState({}, "", "/integrations");
    }
  }, []);

  useEffect(() => {
    loadIntegrations();
    async function loadSyncRuns() {
      setSyncRunsLoading(true);
      setSyncRunsError("");
      if (isDemo()) {
        setSyncRuns(DEMO_SYNC_RUNS);
        setSyncRunsLoading(false);
        return;
      }
      try {
        setSyncRuns(await getSyncRuns(true));
      } catch {
        setSyncRunsError("Recent sync history is unavailable.");
      } finally {
        setSyncRunsLoading(false);
      }
    }
    void loadSyncRuns();
  }, []);

  async function handleSync(key: string) {
    setSyncing((s) => ({ ...s, [key]: true }));
    setSyncMsg((m) => ({ ...m, [key]: "" }));
    try {
      if (isDemo()) {
        setSyncMsg((messages) => ({ ...messages, [key]: "Demo preview only - no external source was changed." }));
        setSyncTone((tones) => ({ ...tones, [key]: "info" }));
        return;
      }
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
      setSyncTone((tones) => ({
        ...tones,
        [key]: res.status === "failed" ? "error" : res.status === "started" ? "info" : "success",
      }));
      loadIntegrations();
    } catch {
      setSyncMsg((m) => ({
        ...m,
        [key]: isDemo()
          ? "Sync triggered (demo mode)"
          : "Sync failed - please try again.",
      }));
      setSyncTone((tones) => ({ ...tones, [key]: "error" }));
    } finally {
      setSyncing((s) => ({ ...s, [key]: false }));
      setTimeout(() => setSyncMsg((m) => ({ ...m, [key]: "" })), 6000);
    }
  }

  async function handleConnectStart(key: string) {
    if (isDemo()) {
      setSyncMsg((messages) => ({ ...messages, [key]: "External connections are disabled in the shared demo workspace." }));
      setSyncTone((tones) => ({ ...tones, [key]: "error" }));
      return;
    }
    if (connecting[key]) return;
    setConnecting((current) => ({ ...current, [key]: true }));
    setSyncMsg((m) => ({ ...m, [key]: "Opening authorization…" }));
    try {
      setSyncTone((tones) => ({ ...tones, [key]: "pending" }));
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
        setSyncTone((tones) => ({ ...tones, [key]: "error" }));
      }
    } catch {
      setSyncMsg((m) => ({
        ...m,
        [key]: "Couldn't reach the server to start authorization. Try again in a moment.",
      }));
      setSyncTone((tones) => ({ ...tones, [key]: "error" }));
    } finally {
      setConnecting((current) => ({ ...current, [key]: false }));
    }
  }

  async function handleToggleConnection(key: string, connect: boolean) {
    if (isDemo()) {
      setSyncMsg((messages) => ({ ...messages, [key]: "Connection changes are disabled in the shared demo workspace." }));
      setSyncTone((tones) => ({ ...tones, [key]: "error" }));
      return;
    }
    if (connect) {
      // Real connect = OAuth handshake via Composio (redirects the browser).
      await handleConnectStart(key);
      return;
    }
    if (connecting[key]) return;
    setConnecting((current) => ({ ...current, [key]: true }));
    // Real disconnect = revoke the Composio connection so a later Connect
    // starts a fresh handshake. Only reflect it in the UI once it succeeds.
    setSyncMsg((m) => ({ ...m, [key]: "Disconnecting…" }));
    try {
      setSyncTone((tones) => ({ ...tones, [key]: "pending" }));
      await composioDisconnect(key);
      setIntegrations((prev) =>
        prev.map((i) =>
          i.key === key
            ? { ...i, auth_state: "not_configured", sync_error: null, last_sync: null }
            : i
        )
      );
      setSyncMsg((m) => ({ ...m, [key]: "Disconnected" }));
      setSyncTone((tones) => ({ ...tones, [key]: "success" }));
    } catch {
      setSyncMsg((m) => ({ ...m, [key]: "Couldn't disconnect - try again" }));
      setSyncTone((tones) => ({ ...tones, [key]: "error" }));
    } finally {
      setConnecting((current) => ({ ...current, [key]: false }));
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
            Connect your company tools to start indexing context. Who can see an
            uploaded file is managed on the file itself, from Ask.
          </p>
        </div>
        <Button
          size="lg"
          className="min-w-[152px] shadow-sm"
          onClick={() => setCatalogOpen(true)}
          disabled={demo}
          title={demo ? "External connections are disabled in the shared demo workspace." : undefined}
        >
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

      {loadError && (
        <div className="card async-state" role="alert">
          <div>
            <p className="error-text" style={{ marginBottom: 12 }}>{loadError}</p>
            <button type="button" className="btn btn-primary" onClick={loadIntegrations}>Retry</button>
          </div>
        </div>
      )}
      {loading && !loadError && (
        <div className="card async-state" role="status" aria-live="polite">Loading integrations…</div>
      )}

      <div hidden={loading || !!loadError}>
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
                {demo
                  ? Object.values(DEMO_STATS.docsPerConnector).reduce((a, b) => a + b, 0).toLocaleString()
                  : metricsAvailable
                    ? Object.values(docsByConnector).reduce((a, b) => a + b, 0).toLocaleString()
                    : "Unavailable"}
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
              <SheldonMascot state="syncing" size={96} className="empty-state-mascot" />
              <p className="text-body font-semibold" style={{ marginBottom: 6 }}>No connectors yet</p>
              <p className="meta" style={{ maxWidth: 420, margin: "0 auto" }}>
                Add a connector to start indexing context from Notion, Google Drive, Slack, and more.
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
                         type="button"
                         className="btn btn-primary btn-sm"
                        disabled={syncing[item.key]}
                        onClick={() => handleSync(item.key)}
                      >
                        {syncing[item.key] ? "Syncing…" : "Sync now"}
                      </button>
                    ) : (
                       <button
                         type="button"
                         className="btn btn-primary btn-sm"
                         disabled={!!connecting[item.key]}
                         onClick={() => handleConnectStart(item.key)}
                         aria-busy={!!connecting[item.key]}
                       >
                         {connecting[item.key] ? "Opening…" : "Connect"}
                      </button>
                    )}
                     <button
                       type="button"
                       className="btn btn-sm"
                      onClick={() => setManagedKey(item.key)}
                    >
                      Manage
                    </button>
                    {syncMsg[item.key] && (
                      <ConnectorFeedback message={syncMsg[item.key]} tone={syncTone[item.key] ?? "info"} />
                    )}
                  </div>
                </div>
              );
            })}

          </div>

          <ConnectorManager
            integration={managed}
            demo={demo}
            open={managedKey !== null}
            onOpenChange={(o) => setManagedKey(o ? managedKey : null)}
            recentRuns={managedRuns}
            recentRunsLoading={syncRunsLoading}
            recentRunsError={syncRunsError}
            syncing={managedKey ? !!syncing[managedKey] : false}
            connectionBusy={managedKey ? !!connecting[managedKey] : false}
            syncMessage={managedKey ? syncMsg[managedKey] ?? "" : ""}
            syncTone={managedKey ? syncTone[managedKey] ?? "info" : "info"}
            onSync={handleSync}
            onToggleConnection={handleToggleConnection}
          />
      </div>
    </div>
  );
}
