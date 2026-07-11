import * as React from "react";
import { Lock } from "lucide-react";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { SourceCitation } from "@/lib/types";
import { brandText, cn } from "@/lib/utils";

/**
 * Compact, clickable citation chip. If the citation has a URL it opens the
 * source in a new tab; otherwise it renders as a static chip.
 */
export function CitationChip({
  citation,
  index,
}: {
  citation: SourceCitation;
  index: number;
}) {
  const meta = CONNECTOR_META[citation.source_tool];
  const Icon = meta?.icon;
  const pct = Math.round(citation.confidence * 100);
  const localOnly = citation.model_routing === "local-only";
  // Policy explain: hover answers "why can I see this, and where did it go?"
  const policyLines = [
    citation.access_reason ? `Visible: ${citation.access_reason}` : null,
    citation.routing_reason ? `Routing: ${citation.routing_reason}` : null,
  ].filter(Boolean);

  const inner = (
    <>
      <span className="text-muted-foreground tabular-nums">[{index + 1}]</span>
      {meta && (
        <span aria-hidden className="inline-flex items-center" style={{ color: meta.color }}>
          {Icon && <Icon className="size-3.5" strokeWidth={1.8} />}
        </span>
      )}
      <span className="min-w-0 flex-1 truncate font-medium text-foreground">
        {brandText(citation.source_record_title)}
      </span>
      <span className="text-muted-foreground tabular-nums">{pct}%</span>
      {localOnly && (
        <span
          aria-label="Processed by local models only"
          className="inline-flex items-center text-muted-foreground"
        >
          <Lock className="size-3" strokeWidth={2} />
        </span>
      )}
    </>
  );

  const className = cn(
    "inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--bg-surface)] px-2.5 py-1 text-[13px] font-medium tracking-[-0.13px] transition-colors",
    citation.url && "hover:border-[var(--border-hover)] cursor-pointer"
  );

  if (citation.url) {
    return (
      <a
        href={citation.url}
        target="_blank"
        rel="noopener noreferrer"
        className={className}
        title={[`${meta?.label ?? citation.source_tool} - open source`, ...policyLines].join("\n")}
      >
        {inner}
      </a>
    );
  }

  return (
    <span
      className={className}
      title={[meta?.label ?? citation.source_tool, ...policyLines].join("\n")}
    >
      {inner}
    </span>
  );
}
