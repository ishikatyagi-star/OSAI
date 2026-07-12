"use client";

import { useEffect, useState } from "react";
import { Bookmark, Download, MessageSquarePlus, Trash2 } from "lucide-react";
import { deleteArtifact, listArtifacts, type SavedArtifactRow } from "@/lib/api";
import { OpenUiArtifacts } from "@/components/ask/openui-artifacts";
import type { AskUiArtifact } from "@/lib/types";
import { Button } from "@/components/ui/button";

/** Saved artifacts: pinned answer outputs (tables, briefs, plans) that
 * outlive their conversation — exportable and reusable as Ask context. */
export default function ArtifactsPage() {
  const [rows, setRows] = useState<SavedArtifactRow[]>([]);
  const [loading, setLoading] = useState(true);

  async function reload() {
    setLoading(true);
    try {
      setRows(await listArtifacts());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    reload();
  }, []);

  function exportMarkdown(a: SavedArtifactRow) {
    const art = a.data as unknown as AskUiArtifact;
    const lines: string[] = [`# ${a.title}`, ""];
    if (art.subtitle) lines.push(art.subtitle, "");
    for (const m of art.metrics ?? []) lines.push(`- **${m.label}**: ${m.value}`);
    if (art.rows?.length) {
      lines.push("", "| Item | Value | Meta |", "|---|---|---|");
      for (const r of art.rows) lines.push(`| ${r.label} | ${r.value} | ${r.meta ?? ""} |`);
    }
    const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const el = document.createElement("a");
    el.href = url;
    el.download = `${a.title.replace(/[^\w-]+/g, "-").toLowerCase()}.md`;
    el.click();
    URL.revokeObjectURL(url);
  }

  function askAbout(a: SavedArtifactRow) {
    window.location.href = `/ask?q=${encodeURIComponent(
      `Using the saved artifact "${a.title}", `
    )}`;
  }

  async function remove(id: string) {
    await deleteArtifact(id);
    reload();
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Artifacts</h1>
          <p>
            Outputs you pinned from Ask answers — tables, briefs, and plans that stay
            useful after the conversation ends.
          </p>
        </div>
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : rows.length === 0 ? (
        <div className="card" style={{ padding: 24, textAlign: "center" }}>
          <Bookmark className="mx-auto mb-2 size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Nothing pinned yet. Click “Save” on any table or brief in an Ask answer.
          </p>
        </div>
      ) : (
        <div className="grid gap-4">
          {rows.map((a) => (
            <div key={a.id} className="card" style={{ padding: "12px 16px" }}>
              <div className="mb-1 flex items-center justify-between gap-3">
                <span className="text-xs text-muted-foreground">
                  {a.created_at ? new Date(a.created_at).toLocaleString() : ""}
                  {a.created_by_name ? ` · pinned by ${a.created_by_name}` : ""}
                </span>
                <div className="flex gap-1.5">
                  <Button size="sm" variant="ghost" onClick={() => askAbout(a)}>
                    <MessageSquarePlus className="size-3.5" /> Ask about this
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => exportMarkdown(a)}>
                    <Download className="size-3.5" /> Export
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-destructive"
                    aria-label={`Delete ${a.title}`}
                    onClick={() => remove(a.id)}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              </div>
              <OpenUiArtifacts artifacts={[a.data as unknown as AskUiArtifact]} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
