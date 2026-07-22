"use client";

import * as React from "react";
import { Check, ExternalLink, Loader2, X, Zap } from "lucide-react";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { AgentAction } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { brandText, cn } from "@/lib/utils";

/**
 * Action-confirmation card. For proposed actions that require confirmation it
 * renders Approve / Dismiss. Reflects executed / failed / skipped states once
 * resolved.
 */
export function ActionCard({
  action,
  busyOperation,
  onApprove,
  onDismiss,
}: {
  action: AgentAction;
  busyOperation?: "approve" | "dismiss" | null;
  onApprove: (action: AgentAction) => void;
  onDismiss: (action: AgentAction) => void;
}) {
  const meta = CONNECTOR_META[action.tool];
  const ConnectorIcon = meta?.icon;
  const isPending = action.status === "proposed" && action.requires_confirmation;
  const busy = busyOperation != null;

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
        "ask-action-card rounded-[15px] border bg-[var(--bg-surface)] p-4",
        isPending ? "border-warning/40" : "border-[var(--border)]"
      )}
    >
      <div className="ask-action-layout flex items-start gap-3">
        <div
          className="ask-action-icon mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md border border-[var(--border)] bg-[var(--bg-surface)] text-base"
          style={meta ? { color: meta.color } : undefined}
          aria-hidden
        >
          {ConnectorIcon ? (
            <ConnectorIcon className="size-4" strokeWidth={1.8} />
          ) : (
            <Zap className="size-4 text-primary" />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="ask-action-header flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-muted-foreground">
              {meta?.label ?? action.tool} · <span className="capitalize">{action.action.replaceAll("_", " ")}</span>
            </span>
            <span aria-live="polite" aria-atomic="true">
              {statusBadge}
            </span>
          </div>
          <p className="ask-action-summary mt-1.5 text-sm leading-relaxed text-foreground/90">{brandText(action.summary)}</p>

          {action.params && Object.keys(action.params).length > 0 && (
            <dl className="ask-action-params mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-md bg-[var(--bg-elevated)] p-3 text-xs">
              {Object.entries(action.params).map(([k, v]) => (
                <React.Fragment key={k}>
                  <dt className="font-mono text-muted-foreground">{k}</dt>
                  <dd className="min-w-0 break-words text-foreground/80">{brandText(String(v))}</dd>
                </React.Fragment>
              ))}
            </dl>
          )}

          {action.error && (
            <p role="alert" className="mt-2 text-xs text-destructive">
              {brandText(action.error)}
            </p>
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
            <div className="ask-action-buttons mt-3 flex items-center gap-2">
              <Button
                size="sm"
                className="min-w-[72px] border-0"
                onClick={() => onApprove(action)}
                disabled={busy}
              >
                {busyOperation === "approve" ? (
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
                variant="outline"
                className="min-w-[72px]"
                onClick={() => onDismiss(action)}
                disabled={busy}
              >
                {busyOperation === "dismiss" ? (
                  <>
                    <Loader2 className="size-3.5 animate-spin" /> Dismissing{"\u2026"}
                  </>
                ) : (
                  "Dismiss"
                )}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
