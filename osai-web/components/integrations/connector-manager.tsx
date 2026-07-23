"use client";

import { useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  FileText,
  Info,
  Loader2,
  Plug,
  PlugZap,
  RefreshCw,
  XCircle,
} from "lucide-react";
import {
  getConnectorDocuments,
  getHealthcheck,
  type ConnectorDocument,
} from "@/lib/api";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { Integration, SyncRun } from "@/lib/types";
import { brandText, timeAgo } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

type Health = { healthy: boolean; message: string } | null;

// Shared timeAgo treats the backend's offset-less UTC timestamps correctly
// (a local copy here was the source of the "synced 5h ago" QA finding).
const relativeTime = timeAgo;

const RUN_TONE: Record<SyncRun["status"], string> = {
  succeeded: "text-success",
  running: "text-info",
  failed: "text-destructive",
};

export function ConnectorManager({
  integration,
  demo,
  canManage,
  canOAuthConnect,
  canSync,
  canDisconnect,
  open,
  onOpenChange,
  recentRuns,
  recentRunsLoading,
  recentRunsError,
  syncing,
  connectionBusy,
  syncMessage = "",
  syncTone = "info",
  onSync,
  onToggleConnection,
}: {
  integration: Integration | null;
  demo: boolean;
  canManage: boolean;
  canOAuthConnect: boolean;
  canSync: boolean;
  canDisconnect: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  recentRuns: SyncRun[];
  recentRunsLoading: boolean;
  recentRunsError?: string;
  syncing: boolean;
  connectionBusy: boolean;
  syncMessage?: string;
  syncTone?: "pending" | "success" | "error" | "info";
  onSync: (key: string) => void;
  onToggleConnection: (key: string, connect: boolean) => void;
}) {
  const [health, setHealth] = useState<Health>(null);
  const [checking, setChecking] = useState(false);
  const [healthError, setHealthError] = useState("");

  // Recently synced files for this connector.
  const [docs, setDocs] = useState<ConnectorDocument[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [docsError, setDocsError] = useState("");
  const healthRequestRef = useRef(0);
  const docsRequestRef = useRef(0);

  const meta =
    integration && CONNECTOR_META[integration.key]
      ? CONNECTOR_META[integration.key]
      : null;
  const ConnectorIcon = meta?.icon ?? Plug;
  const connected = integration?.auth_state === "connected";
  // An expired connection still has a Composio account to revoke, so it must
  // remain disconnectable, otherwise the card is stuck (can't sync, can't
  // remove). Disconnect is offered for both connected and expired states.
  const disconnectable =
    (connected || integration?.auth_state === "expired") && canDisconnect;

  async function runHealthcheck(key: string) {
    const requestId = ++healthRequestRef.current;
    setChecking(true);
    setHealthError("");
    try {
      const nextHealth = await getHealthcheck(key, true);
      if (requestId !== healthRequestRef.current) return;
      setHealth(nextHealth);
    } catch {
      if (requestId !== healthRequestRef.current) return;
      setHealth(null);
      setHealthError("Connection health could not be checked.");
    } finally {
      if (requestId === healthRequestRef.current) setChecking(false);
    }
  }

  async function loadDocuments(key: string) {
    const requestId = ++docsRequestRef.current;
    setDocsLoading(true);
    setDocsError("");
    try {
      const nextDocs = await getConnectorDocuments(key, true);
      if (requestId !== docsRequestRef.current) return;
      setDocs(nextDocs);
    } catch {
      if (requestId !== docsRequestRef.current) return;
      setDocs([]);
      setDocsError("Synced files could not be loaded.");
    } finally {
      if (requestId === docsRequestRef.current) setDocsLoading(false);
    }
  }

  // Auto health-check + load synced files whenever a connected connector opens.
  useEffect(() => {
    if (open && integration && integration.auth_state === "connected" && canSync) {
      if (demo) {
        healthRequestRef.current += 1;
        docsRequestRef.current += 1;
        setChecking(false);
        setHealthError("");
        setHealth({ healthy: true, message: "Sample status for this demo." });
        setDocs([]);
        setDocsError("");
        setDocsLoading(false);
      } else {
        void runHealthcheck(integration.key);
        void loadDocuments(integration.key);
      }
    } else {
      healthRequestRef.current += 1;
      docsRequestRef.current += 1;
      setHealth(null);
      setHealthError("");
      setDocs([]);
      setDocsError("");
      setDocsLoading(false);
    }
    return () => {
      healthRequestRef.current += 1;
      docsRequestRef.current += 1;
    };
  }, [open, integration, demo, canSync]);

  if (!integration) return null;

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !connectionBusy && onOpenChange(nextOpen)}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div
              className="flex size-10 items-center justify-center rounded-lg border border-border bg-secondary text-muted-foreground"
              aria-hidden
            >
              <ConnectorIcon className="size-5" strokeWidth={1.8} />
            </div>
            <div>
              <DialogTitle>{brandText(meta?.label ?? integration.display_name)}</DialogTitle>
              <DialogDescription>
                {!canSync && !canOAuthConnect
                  ? "Legacy connection unavailable"
                  : integration.auth_state === "expired"
                    ? "Connection expired"
                  : connected
                  ? integration.account_email
                    ? `Connected as ${integration.account_email}`
                    : "Connected"
                  : "Not connected"}
                {integration.last_sync &&
                  ` · last synced ${relativeTime(integration.last_sync)}`}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {connected && integration.previous_account_email && (
          <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-2.5 py-2 text-[11px] text-foreground/80">
            Reconnected with a different account
            {integration.last_reconnected_at
              ? ` ${relativeTime(integration.last_reconnected_at)}`
              : ""}
            . Files from <span className="font-medium">{integration.previous_account_email}</span>{" "}
            were removed from the knowledge base; only{" "}
            <span className="font-medium">{integration.account_email ?? "the current account"}</span>{" "}
            is searchable now.
          </div>
        )}

        {/* Scopes / capabilities */}
        <section>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Capabilities &amp; scopes
          </p>
          <div className="flex flex-wrap gap-1.5">
            {integration.capabilities?.map((c) => (
              <Badge key={c} variant="secondary">
                {c}
              </Badge>
            ))}
            {integration.scopes?.map((s) => (
              <Badge key={s} variant="muted">
                {s}
              </Badge>
            ))}
            {!integration.capabilities?.length && !integration.scopes?.length && (
              <span className="text-xs text-muted-foreground">
                No scopes granted yet.
              </span>
            )}
          </div>
        </section>

        {/* Health */}
        {connected && canSync && (
          <section className="rounded-lg border border-border bg-background/40 p-3">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <Activity className="size-3.5" /> Connection health
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="h-10"
                disabled={checking || demo}
                title={demo ? "Health checks are disabled for sample connectors." : undefined}
                onClick={() => runHealthcheck(integration.key)}
              >
                {checking ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="size-3.5" />
                )}
                Re-check
              </Button>
            </div>
            <div className="mt-2 flex items-center gap-2 text-sm">
              {checking ? (
                <span className="text-muted-foreground">Checking…</span>
              ) : healthError ? (
                <span className="text-destructive" role="alert">{healthError}</span>
              ) : health ? (
                <>
                  {health.healthy ? (
                    <CheckCircle2 className="size-4 text-success" />
                  ) : (
                    <XCircle className="size-4 text-destructive" />
                  )}
                  <span
                    className={health.healthy ? "text-success" : "text-destructive"}
                  >
                    {brandText(health.message)}
                  </span>
                </>
              ) : (
                <span className="text-muted-foreground">Not checked yet.</span>
              )}
            </div>
            {integration.sync_error && (
              <p className="mt-2 inline-flex items-start gap-1.5 text-xs text-destructive">
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0" strokeWidth={1.8} />
                <span>{brandText(integration.sync_error)}</span>
              </p>
            )}
          </section>
        )}

        {/* Recent syncs */}
        {connected && canSync && (
          <section>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Recent syncs
            </p>
            {recentRunsLoading ? (
              <p className="text-xs text-muted-foreground" role="status">Loading sync history...</p>
            ) : recentRunsError ? (
              <p className="text-xs text-destructive" role="alert">{recentRunsError}</p>
            ) : recentRuns.length === 0 ? (
              <p className="text-xs text-muted-foreground">No sync runs yet.</p>
            ) : (
              <ul className="space-y-1">
                {recentRuns.slice(0, 4).map((r) => (
                  <li
                    key={r.id}
                    className="flex items-center justify-between rounded-md border border-border bg-background/40 px-2.5 py-1.5 text-xs"
                  >
                    <span className={`font-medium capitalize ${RUN_TONE[r.status]}`}>
                      {r.status}
                    </span>
                    <span className="text-muted-foreground">
                      {r.documents_indexed}/{r.documents_seen} docs ·{" "}
                      {relativeTime(r.started_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {/* Synced files */}
        {connected && canSync && (
          <section className="rounded-lg border border-border bg-background/40 p-3">
            <p className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              <FileText className="size-3.5" /> Synced files{demo || docsLoading || docsError ? "" : ` (${docs.length})`}
            </p>
            {demo ? (
              <p className="text-xs text-muted-foreground">
                File-level examples are hidden in the shared demo. The sample indexed total is shown on the connector card.
              </p>
            ) : docsLoading ? (
              <p className="text-xs text-muted-foreground" role="status">Loading synced files...</p>
            ) : docsError ? (
              <p className="text-xs text-destructive" role="alert">{docsError}</p>
            ) : docs.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                {canSync
                  ? "Nothing indexed yet - click \"Sync now\" to pull in this source."
                  : "This legacy connector is unavailable for indexing."}
              </p>
            ) : (
              <ul className="max-h-52 space-y-1 overflow-y-auto">
                {docs.map((d) => (
                  <li
                    key={d.id}
                    className="flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs"
                  >
                    <span className="min-w-0 flex-1 truncate text-foreground/90">
                      {d.url ? (
                        <a href={d.url} target="_blank" rel="noreferrer" className="hover:underline">
                          {brandText(d.title)}
                        </a>
                      ) : (
                        brandText(d.title)
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {canManage && <Separator />}

        {/* Admin-only actions; the API remains the security boundary. */}
        {canManage ? <div className="flex items-center justify-between gap-2">
          {disconnectable ? (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              disabled={demo || connectionBusy}
              title={demo ? "Connection changes are disabled in the shared demo workspace." : undefined}
              onClick={() => onToggleConnection(integration.key, false)}
              aria-label={`Disconnect ${brandText(meta?.label ?? integration.display_name)}`}
            >
              {connectionBusy ? <Loader2 className="size-3.5 animate-spin" /> : <Plug className="size-3.5" />}
              {connectionBusy ? "Disconnecting..." : "Disconnect"}
            </Button>
          ) : !connected && canOAuthConnect ? (
            <span className="text-xs text-muted-foreground">
              Authorize to start indexing this source.
            </span>
          ) : connected && canSync ? (
            <span className="text-xs text-muted-foreground">
              Connection settings are managed by your deployment administrator.
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">
              This legacy connector is unavailable for indexing.
            </span>
          )}

          {connected && canSync ? (
            <Button
              size="sm"
              disabled={syncing}
              onClick={() => onSync(integration.key)}
            >
              {syncing ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" /> Syncing…
                </>
              ) : (
                <>
                  <RefreshCw className="size-3.5" /> Sync now
                </>
              )}
            </Button>
          ) : canOAuthConnect ? (
            <Button
              size="sm"
              disabled={demo || connectionBusy}
              title={demo ? "External connections are disabled in the shared demo workspace." : undefined}
              onClick={() => onToggleConnection(integration.key, true)}
              aria-label={`${integration.auth_state === "expired" ? "Reconnect" : "Connect"} ${brandText(meta?.label ?? integration.display_name)}`}
            >
              {connectionBusy ? <Loader2 className="size-3.5 animate-spin" /> : <PlugZap className="size-3.5" />}
              {connectionBusy ? "Opening..." : integration.auth_state === "expired" ? "Reconnect" : "Connect"}
            </Button>
          ) : null}
        </div> : (
          <p className="text-xs text-muted-foreground">
            Only workspace admins can sync or change this connection.
          </p>
        )}
        {syncMessage && (
          <p
            className="-mt-2 text-[12px] inline-flex items-center gap-1.5"
            role={syncTone === "error" ? "alert" : "status"}
            aria-live="polite"
            style={{
              color:
                syncTone === "error"
                  ? "var(--red)"
                  : syncTone === "pending"
                    ? "var(--blue)"
                    : syncTone === "info"
                      ? "var(--blue)"
                      : "var(--green)",
            }}
          >
            {syncTone === "error" ? (
              <XCircle className="size-3.5" />
            ) : syncTone === "info" ? (
              <Info className="size-3.5" />
            ) : syncTone === "pending" ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <CheckCircle2 className="size-3.5" />
            )}
            {brandText(syncMessage)}
          </p>
        )}
        {!connected && canManage && canOAuthConnect && (
          <p className="-mt-2 text-[11px] text-muted-foreground">
            Connect redirects you to {meta?.label ?? "the provider"} to authorize
            access. Sheldon indexes and searches your content; it never edits or
            deletes existing items.
            {integration.capabilities?.includes("execute") &&
              " This connector can also create new items (tickets, messages, pages) - only when you approve a proposed action."}
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
