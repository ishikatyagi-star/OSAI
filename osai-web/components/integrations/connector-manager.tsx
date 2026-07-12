"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  FileText,
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
  open,
  onOpenChange,
  recentRuns,
  syncing,
  syncMessage = "",
  onSync,
  onToggleConnection,
}: {
  integration: Integration | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  recentRuns: SyncRun[];
  syncing: boolean;
  syncMessage?: string;
  onSync: (key: string) => void;
  onToggleConnection: (key: string, connect: boolean) => void;
}) {
  const [health, setHealth] = useState<Health>(null);
  const [checking, setChecking] = useState(false);

  // Recently synced files for this connector.
  const [docs, setDocs] = useState<ConnectorDocument[]>([]);

  const meta =
    integration && CONNECTOR_META[integration.key]
      ? CONNECTOR_META[integration.key]
      : null;
  const ConnectorIcon = meta?.icon ?? Plug;
  const connected = integration?.auth_state === "connected";

  async function runHealthcheck(key: string) {
    setChecking(true);
    try {
      setHealth(await getHealthcheck(key));
    } finally {
      setChecking(false);
    }
  }

  // Auto health-check + load synced files whenever a connected connector opens.
  useEffect(() => {
    if (open && integration && integration.auth_state === "connected") {
      runHealthcheck(integration.key);
      getConnectorDocuments(integration.key).then(setDocs);
    } else {
      setHealth(null);
      setDocs([]);
    }
  }, [open, integration]);

  if (!integration) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
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
                {connected
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
        {connected && (
          <section className="rounded-lg border border-border bg-background/40 p-3">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <Activity className="size-3.5" /> Connection health
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="h-10"
                disabled={checking}
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
        {connected && (
          <section>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Recent syncs
            </p>
            {recentRuns.length === 0 ? (
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
        {connected && (
          <section className="rounded-lg border border-border bg-background/40 p-3">
            <p className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              <FileText className="size-3.5" /> Synced files ({docs.length})
            </p>
            {docs.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                Nothing indexed yet - click “Sync now” to pull in this source.
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

        <Separator />

        {/* Actions */}
        <div className="flex items-center justify-between gap-2">
          {connected ? (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => onToggleConnection(integration.key, false)}
            >
              <Plug className="size-3.5" /> Disconnect
            </Button>
          ) : (
            <span className="text-xs text-muted-foreground">
              Authorize to start indexing this source.
            </span>
          )}

          {connected ? (
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
          ) : (
            <Button
              size="sm"
              onClick={() => onToggleConnection(integration.key, true)}
            >
              <PlugZap className="size-3.5" /> Connect
            </Button>
          )}
        </div>
        {syncMessage && (
          <p
            className="-mt-2 text-[12px] inline-flex items-center gap-1.5"
            role="status"
            style={{
              color: /failed/i.test(syncMessage) ? "var(--red)" : "var(--green)",
            }}
          >
            {/failed/i.test(syncMessage) ? (
              <XCircle className="size-3.5" />
            ) : (
              <CheckCircle2 className="size-3.5" />
            )}
            {brandText(syncMessage)}
          </p>
        )}
        {!connected && (
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
