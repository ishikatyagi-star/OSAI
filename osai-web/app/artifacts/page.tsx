"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Bookmark, Download, MessageSquarePlus, Trash2 } from "lucide-react";
import { deleteArtifact, listArtifacts, type SavedArtifactRow } from "@/lib/api";
import { OpenUiArtifacts } from "@/components/ask/openui-artifacts";
import type { AskUiArtifact } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { isDemo } from "@/lib/demo";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/** Saved artifacts: pinned answer outputs (tables, briefs, plans) that
 * outlive their conversation - exportable and reusable as Ask context. */
export default function ArtifactsPage() {
  const router = useRouter();
  const [rows, setRows] = useState<SavedArtifactRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [mutationError, setMutationError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<SavedArtifactRow | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  async function reload() {
    setLoading(true);
    setLoadError("");
    if (isDemo()) {
      setRows([]);
      setLoading(false);
      return;
    }
    try {
      setRows(await listArtifacts(true));
    } catch {
      setLoadError("Saved artifacts could not be loaded. Check your connection and retry.");
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
    router.push(`/ask?q=${encodeURIComponent(
      `Using the saved artifact "${a.title}", `
    )}`);
  }

  async function remove(id: string) {
    if (deleteBusy) return;
    setDeleteBusy(true);
    setMutationError("");
    try {
      await deleteArtifact(id);
      setRows((current) => current.filter((row) => row.id !== id));
      setPendingDelete(null);
    } catch {
      setMutationError("The artifact could not be deleted. Please try again.");
    } finally {
      setDeleteBusy(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Artifacts</h1>
          <p>
            Outputs you pinned from Ask answers - tables, briefs, and plans that stay
            useful after the conversation ends.
          </p>
        </div>
      </div>

      {mutationError && <div className="card" role="alert" style={{ marginBottom: 16, padding: "10px 14px", color: "var(--red)" }}>{mutationError}</div>}

      {loadError ? (
        <div className="card async-state" role="alert">
          <div>
            <p className="error-text" style={{ marginBottom: 12 }}>{loadError}</p>
            <button type="button" className="btn btn-primary" onClick={reload}>Retry</button>
          </div>
        </div>
      ) : loading ? (
        <div className="card async-state" role="status" aria-live="polite">Loading artifacts…</div>
      ) : rows.length === 0 ? (
        <div className="card" style={{ padding: 24, textAlign: "center" }}>
          <Bookmark className="mx-auto mb-2 size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Nothing pinned yet. Click “Save” on any table or brief in an Ask answer.
          </p>
          <Link href="/ask" className="btn btn-primary" style={{ marginTop: 14 }}>Go to Ask Sheldon</Link>
        </div>
      ) : (
        <div className="grid gap-4">
          {rows.map((a) => (
            <div key={a.id} className="card" style={{ padding: "12px 16px" }}>
              <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
                <span className="text-xs text-muted-foreground">
                  {a.created_at ? new Date(a.created_at).toLocaleString() : ""}
                  {a.created_by_name ? ` · pinned by ${a.created_by_name}` : ""}
                </span>
                <div className="flex flex-wrap gap-1.5">
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
                    onClick={() => { setMutationError(""); setPendingDelete(a); }}
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

      {pendingDelete && (
        <Dialog open onOpenChange={(open) => !open && !deleteBusy && setPendingDelete(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete this artifact?</DialogTitle>
              <DialogDescription>“{pendingDelete.title}” will be permanently removed from saved artifacts.</DialogDescription>
            </DialogHeader>
            {mutationError && <p className="error-text" role="alert">{mutationError}</p>}
            <DialogFooter>
              <button type="button" className="btn" onClick={() => setPendingDelete(null)} disabled={deleteBusy}>Cancel</button>
              <button type="button" className="btn btn-danger" onClick={() => remove(pendingDelete.id)} disabled={deleteBusy}>
                {deleteBusy ? "Deletingâ€¦" : "Delete artifact"}
              </button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
