"use client";

import * as React from "react";
import { Check, ExternalLink, Loader2, X, Zap } from "lucide-react";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { AgentAction } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * Action-confirmation card. For proposed actions that require confirmation it
 * renders Approve / Dismiss. Reflects executed / failed / skipped states once
 * resolved.
 */
export function ActionCard({
  action,
  busy,
  onApprove,
  onDismiss,
}: {
  action: AgentAction;
  busy?: boolean;
  onApprove: (action: AgentAction) => void;
  onDismiss: (action: AgentAction) => void;
}) {
  const meta = CONNECTOR_META[action.tool];
  const isPending = action.status === "proposed" && action.requires_confirmation;

  const statusBadge = {
    proposed: <Badge variant="warning">Needs approval</Badge>,
    executed: (
      <Badge variant="success">
        <Check /> Executed
      </Badge>
    ),
    failed: (
      <Badge variant="destructive">
        <X /> Failed
      </Badge>
    ),
    skipped: <Badge variant="muted">Dismissed</Badge>,
  }[action.status];

  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-3.5",
        isPending ? "border-warning/40" : "border-border"
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-secondary text-base"
          style={meta ? { color: meta.color } : undefined}
          aria-hidden
        >
          {meta?.icon ?? <Zap className="size-4 text-primary" />}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {meta?.label ?? action.tool} · {action.action}
            </span>
            {statusBadge}
          </div>
          <p className="mt-1 text-sm text-foreground/90">{action.summary}</p>

          {action.params && Object.keys(action.params).length > 0 && (
            <dl className="mt-2.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-md border border-border bg-background/40 p-2.5 text-xs">
              {Object.entries(action.params).map(([k, v]) => (
                <React.Fragment key={k}>
                  <dt className="font-mono text-muted-foreground">{k}</dt>
                  <dd className="truncate text-foreground/80">{String(v)}</dd>
                </React.Fragment>
              ))}
            </dl>
          )}

          {action.error && (
            <p className="mt-2 text-xs text-destructive">{action.error}</p>
          )}

          {action.external_url && (
            <a
              href={action.external_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              <ExternalLink className="size-3" />
              View in {meta?.label ?? action.tool}
            </a>
          )}

          {isPending && (
            <div className="mt-3 flex items-center gap-2">
              <Button
                size="sm"
                onClick={() => onApprove(action)}
                disabled={busy}
              >
                {busy ? (
                  <>
                    <Loader2 className="size-3.5 animate-spin" /> Approving…
                  </>
                ) : (
                  <>
                    <Check className="size-3.5" /> Approve
                  </>
                )}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onDismiss(action)}
                disabled={busy}
              >
                Dismiss
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
