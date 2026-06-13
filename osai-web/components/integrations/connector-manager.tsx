"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Loader2,
  Plug,
  PlugZap,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { getHealthcheck } from "@/lib/api";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { Integration, SyncRun } from "@/lib/types";
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

function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

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
  onSync,
  onToggleConnection,
}: {
  integration: Integration | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  recentRuns: SyncRun[];
  syncing: boolean;
  onSync: (key: string) => void;
  onToggleConnection: (key: string, connect: boolean) => void;
}) {
  const [health, setHealth] = useState<Health>(null);
  const [checking, setChecking] = useState(false);

  const meta =
    integration && CONNECTOR_META[integration.key]
      ? CONNECTOR_META[integration.key]
      : null;
  const connected = integration?.auth_state === "connected";

  async function runHealthcheck(key: string) {
    setChecking(true);
    try {
      setHealth(await getHealthcheck(key));
    } finally {
      setChecking(false);
    }
  }

  // Auto health-check whenever a connected connector's manager opens.
  useEffect(() => {
    if (open && integration && integration.auth_state === "connected") {
      runHealthcheck(integration.key);
    } else {
      setHealth(null);
    }
  }, [open, integration]);

  if (!integration) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div
              className="flex size-10 items-center justify-center rounded-lg border border-border bg-secondary text-xl"
              aria-hidden
            >
              {meta?.icon ?? "⚙"}
            </div>
            <div>
              <DialogTitle>{meta?.label ?? integration.display_name}</DialogTitle>
              <DialogDescription>
                {connected ? "Connected" : "Not connected"}
                {integration.last_sync &&
                  ` · last synced ${relativeTime(integration.last_sync)}`}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

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
                className="h-7"
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
                    {health.message}
                  </span>
                </>
              ) : (
                <span className="text-muted-foreground">Not checked yet.</span>
              )}
            </div>
            {integration.sync_error && (
              <p className="mt-2 text-xs text-destructive">
                ⚠ {integration.sync_error}
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
        {!connected && (
          <p className="-mt-2 text-[11px] text-muted-foreground">
            Connecting starts an OAuth handshake handled by the backend; this
            preview marks the connector active locally.
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
