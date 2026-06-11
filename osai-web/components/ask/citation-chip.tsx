import * as React from "react";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { SourceCitation } from "@/lib/types";
import { cn } from "@/lib/utils";

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
  const pct = Math.round(citation.confidence * 100);

  const inner = (
    <>
      <span className="text-muted-foreground tabular-nums">[{index + 1}]</span>
      {meta && (
        <span aria-hidden style={{ color: meta.color }}>
          {meta.icon}
        </span>
      )}
      <span className="max-w-[220px] truncate font-medium text-foreground">
        {citation.source_record_title}
      </span>
      <span className="text-muted-foreground tabular-nums">{pct}%</span>
    </>
  );

  const className = cn(
    "inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-xs transition-colors",
    citation.url && "hover:border-input hover:bg-accent cursor-pointer"
  );

  if (citation.url) {
    return (
      <a
        href={citation.url}
        target="_blank"
        rel="noopener noreferrer"
        className={className}
        title={`${meta?.label ?? citation.source_tool} — open source`}
      >
        {inner}
      </a>
    );
  }

  return (
    <span className={className} title={meta?.label ?? citation.source_tool}>
      {inner}
    </span>
  );
}
