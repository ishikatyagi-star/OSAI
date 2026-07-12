"use client";

import { useState } from "react";
import {
  BarChart3,
  Bookmark,
  BookmarkCheck,
  CheckCircle2,
  ExternalLink,
  FileText,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { saveArtifact } from "@/lib/api";
import { isDemo } from "@/lib/demo";
import {
  Callout,
  Card,
  CardHeader,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tag,
  TagBlock,
} from "@openuidev/react-ui";
import type { AskUiArtifact, AskUiArtifactMetric, AskUiArtifactRow } from "@/lib/types";
import { brandText } from "@/lib/utils";

const TONE_TO_TAG: Record<
  NonNullable<AskUiArtifactMetric["tone"]>,
  "neutral" | "info" | "success" | "warning" | "danger"
> = {
  neutral: "neutral",
  info: "info",
  success: "success",
  warning: "warning",
  danger: "danger",
};

function formatConfidence(value: number | null | undefined) {
  if (typeof value !== "number" || Number.isNaN(value)) return "n/a";
  return `${Math.round(value * 100)}%`;
}

function ArtifactIcon({ kind }: { kind: AskUiArtifact["kind"] }) {
  if (kind === "source_table") return <FileText className="size-4" />;
  if (kind === "action_plan") return <CheckCircle2 className="size-4" />;
  if (kind === "context_gap") return <ShieldAlert className="size-4" />;
  return <Sparkles className="size-4" />;
}

function MetricTags({ metrics }: { metrics: AskUiArtifactMetric[] }) {
  return (
    <TagBlock className="ask-openui-tags">
      {metrics.map((metric) => (
        <Tag
          key={metric.label}
          size="sm"
          variant={TONE_TO_TAG[metric.tone ?? "neutral"]}
          text={brandText(`${metric.label}: ${metric.value}`)}
        />
      ))}
    </TagBlock>
  );
}

function ArtifactRows({ rows }: { rows: AskUiArtifactRow[] }) {
  const showsConfidence = rows.some((row) => row.confidence != null);

  return (
    <Table containerClassName="ask-openui-table-wrap">
      <TableHeader>
        <TableRow>
          <TableHead>Item</TableHead>
          <TableHead>Source / tool</TableHead>
          <TableHead align="right">{showsConfidence ? "Confidence" : "Status"}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, index) => (
          <TableRow key={`${row.label}-${index}`}>
            <TableCell>
              <span className="ask-openui-row-title">
                {row.href ? (
                  <a href={row.href} target="_blank" rel="noreferrer">
                    {brandText(row.label)}
                    <ExternalLink className="size-3" />
                  </a>
                ) : (
                  brandText(row.label)
                )}
              </span>
              {showsConfidence && row.meta && (
                <span className="ask-openui-row-meta">{brandText(row.meta)}</span>
              )}
            </TableCell>
            <TableCell>
              <Tag
                size="sm"
                variant={TONE_TO_TAG[row.tone ?? "neutral"]}
                text={brandText(row.value)}
              />
            </TableCell>
            <TableCell align="right">
              {showsConfidence ? formatConfidence(row.confidence) : row.meta ?? ""}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function PinButton({ artifact }: { artifact: AskUiArtifact }) {
  const [pinned, setPinned] = useState(false);
  const [busy, setBusy] = useState(false);
  if (isDemo()) return null;
  return (
    <button
      type="button"
      className="ask-openui-pin inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
      aria-label={pinned ? "Saved to Artifacts" : `Save "${artifact.title}" to Artifacts`}
      disabled={pinned || busy}
      onClick={async () => {
        setBusy(true);
        try {
          await saveArtifact({
            title: artifact.title,
            kind: artifact.kind,
            data: artifact as unknown as Record<string, unknown>,
          });
          setPinned(true);
        } finally {
          setBusy(false);
        }
      }}
    >
      {pinned ? <BookmarkCheck className="size-3.5" /> : <Bookmark className="size-3.5" />}
      {pinned ? "Saved" : "Save"}
    </button>
  );
}

export function OpenUiArtifacts({ artifacts }: { artifacts?: AskUiArtifact[] }) {
  if (!artifacts?.length) return null;

  return (
    <div className="ask-openui-shell" aria-label="OpenUI generated workspace artifacts">
      <div className="ask-openui-heading">
        <BarChart3 className="size-3.5" />
        <span>OpenUI workspace</span>
      </div>
      <div className="ask-openui-grid">
        {artifacts.map((artifact) =>
          artifact.kind === "context_gap" ? (
            <Callout
              key={artifact.id}
              variant="warning"
              title={brandText(artifact.title)}
              description={brandText(artifact.subtitle)}
              className="ask-openui-callout"
            />
          ) : (
            <Card key={artifact.id} variant="card" width="full" className="ask-openui-card">
              <CardHeader
                icon={<ArtifactIcon kind={artifact.kind} />}
                title={brandText(artifact.title)}
                subtitle={brandText(artifact.subtitle)}
              />
              {artifact.metrics?.length ? <MetricTags metrics={artifact.metrics} /> : null}
              {artifact.rows?.length ? <ArtifactRows rows={artifact.rows} /> : null}
              <div className="flex justify-end pt-1">
                <PinButton artifact={artifact} />
              </div>
            </Card>
          )
        )}
      </div>
    </div>
  );
}
