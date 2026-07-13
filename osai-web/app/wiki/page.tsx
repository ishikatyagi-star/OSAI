"use client";

import { useEffect, useRef, useState } from "react";
import { BookOpen, Check, History, Loader2, Plus, Trash2, X } from "lucide-react";
import {
  createWikiEntry,
  deleteWikiEntry,
  getWikiEntries,
  getWikiRevisions,
  updateWikiEntry,
  type WikiEntry,
  type WikiRevisionRow,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { isDemo } from "@/lib/demo";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const ORIGIN_LABEL: Record<WikiEntry["origin"], string> = {
  manual: "written by hand",
  decision: "from a logged decision",
  correction: "from an answer correction",
};

/** The org wiki ("Context"): curated, versioned knowledge that Ask cites.
 * Suggestions drafted from real work (decisions, corrections) await approval
 * at the top; published entries are editable with full revision history. */
export default function WikiPage() {
  const demo = isDemo();
  const [entries, setEntries] = useState<WikiEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<WikiEntry | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [revisionsFor, setRevisionsFor] = useState<string | null>(null);
  const [revisions, setRevisions] = useState<WikiRevisionRow[]>([]);
  const [revisionsLoading, setRevisionsLoading] = useState(false);
  const [revisionsError, setRevisionsError] = useState("");
  const revisionsRequestRef = useRef(0);
  const [loadError, setLoadError] = useState("");
  const [mutationError, setMutationError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<WikiEntry | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  async function reload() {
    setLoading(true);
    setLoadError("");
    if (demo) {
      setEntries([]);
      setLoading(false);
      return;
    }
    try {
      setEntries(await getWikiEntries(true));
    } catch {
      setLoadError("Wiki entries could not be loaded. Check your connection and retry.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    reload();
  }, []);

  const suggestions = entries.filter((e) => e.status === "suggested");
  const published = entries.filter((e) => e.status === "published");

  function cancelEdit() {
    setEditing(null);
    setCreating(false);
  }

  function startEdit(e: WikiEntry | null) {
    setEditing(e);
    setCreating(e === null);
    setDraftTitle(e?.title ?? "");
    setDraftContent(e?.content ?? "");
    setRevisionsFor(null);
  }

  async function save() {
    if (demo) {
      setMutationError("Wiki changes are disabled in the shared demo. Sign in to edit your workspace wiki.");
      return;
    }
    if (!draftTitle.trim() || !draftContent.trim() || busy) return;
    setBusy(true);
    setMutationError("");
    try {
      if (creating) {
        await createWikiEntry({ title: draftTitle, content: draftContent });
      } else if (editing) {
        await updateWikiEntry(editing.id, { title: draftTitle, content: draftContent });
      }
      cancelEdit();
      await reload();
    } catch {
      setMutationError("The wiki entry could not be saved. Your draft is still open; please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function approve(id: string) {
    if (demo) {
      setMutationError("Wiki changes are disabled in the shared demo. Sign in to edit your workspace wiki.");
      return;
    }
    setMutationError("");
    try {
      await updateWikiEntry(id, { status: "published" });
      reload();
    } catch {
      setMutationError("The suggestion could not be approved. Please try again.");
    }
  }

  async function remove(id: string) {
    if (demo || deleteBusy) {
      if (demo) setMutationError("Wiki changes are disabled in the shared demo. Sign in to edit your workspace wiki.");
      return;
    }
    setDeleteBusy(true);
    setMutationError("");
    try {
      await deleteWikiEntry(id);
      setEntries((current) => current.filter((entry) => entry.id !== id));
      setPendingDelete(null);
    } catch {
      setMutationError("The wiki entry could not be deleted. Please try again.");
    } finally {
      setDeleteBusy(false);
    }
  }

  async function showRevisions(id: string) {
    const requestId = ++revisionsRequestRef.current;
    setRevisionsFor(id);
    setRevisions([]);
    setRevisionsError("");
    setRevisionsLoading(true);
    try {
      const nextRevisions = await getWikiRevisions(id, true);
      if (requestId === revisionsRequestRef.current) setRevisions(nextRevisions);
    } catch {
      if (requestId === revisionsRequestRef.current) {
        setRevisionsError("Revision history could not be loaded. Check your connection and retry.");
      }
    } finally {
      if (requestId === revisionsRequestRef.current) setRevisionsLoading(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Wiki</h1>
          <p>
            Curated context Sheldon cites in answers. Suggestions appear here from real
            work - approve them to make them part of your org&apos;s knowledge.
          </p>
        </div>
        <Button onClick={() => startEdit(null)} disabled={demo} title={demo ? "Wiki editing is disabled in the shared demo" : undefined}>
          <Plus size={14} /> New entry
        </Button>
      </div>

      {demo && (
        <div className="card" role="status" style={{ marginBottom: 16, padding: "10px 14px" }}>
          <p className="meta">Wiki editing is disabled in the shared demo. Sign in to curate your workspace knowledge.</p>
        </div>
      )}

      {mutationError && <div className="card" role="alert" style={{ marginBottom: 16, padding: "10px 14px", color: "var(--red)" }}>{mutationError}</div>}

      {(creating || editing) && (
        <div className="card" style={{ marginBottom: 16, padding: 16 }}>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-semibold">
              {creating ? "New entry" : `Edit “${editing?.title}”`}
            </span>
            <Button type="button" size="icon" variant="ghost" aria-label="Close editor" onClick={cancelEdit}>
              <X className="size-4" />
            </Button>
          </div>
          <div className="flex flex-col gap-2">
            <label className="sr-only" htmlFor="wiki-title">Entry title</label>
            <Input
              id="wiki-title"
              name="title"
              placeholder="Title"
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
            />
            <label className="sr-only" htmlFor="wiki-content">Entry content</label>
            <Textarea
              id="wiki-content"
              name="content"
              rows={6}
              placeholder="What should the team (and Sheldon) know?"
              value={draftContent}
              onChange={(e) => setDraftContent(e.target.value)}
            />
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={cancelEdit} disabled={busy}>
                Cancel
              </Button>
              <Button onClick={save} disabled={busy || !draftTitle.trim() || !draftContent.trim()}>
                {busy ? <Loader2 className="size-4 animate-spin" /> : "Save"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {suggestions.length > 0 && (
        <section style={{ marginBottom: 20 }}>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Suggested from your team&apos;s work ({suggestions.length})
          </p>
          <div className="grid gap-2">
            {suggestions.map((e) => (
              <div key={e.id} className="card" style={{ padding: "12px 16px" }}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold">{e.title}</div>
                    <div className="text-xs text-muted-foreground">{ORIGIN_LABEL[e.origin]}</div>
                    <p className="mt-1 whitespace-pre-wrap text-sm">{e.content}</p>
                  </div>
                  <div className="flex flex-wrap shrink-0 gap-1.5">
                    <Button size="sm" onClick={() => approve(e.id)} aria-label={`Approve suggestion: ${e.title}`}>
                      <Check className="size-3.5" /> Approve
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => { setMutationError(""); setPendingDelete(e); }} aria-label={`Dismiss suggestion: ${e.title}`}>
                      Dismiss
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {loadError ? (
        <div className="card async-state" role="alert">
          <div>
            <p className="error-text" style={{ marginBottom: 12 }}>{loadError}</p>
            <button type="button" className="btn btn-primary" onClick={reload}>Retry</button>
          </div>
        </div>
      ) : loading ? (
        <div className="card async-state" role="status" aria-live="polite">Loading wiki entries…</div>
      ) : published.length === 0 ? (
        <div className="card" style={{ padding: 24, textAlign: "center" }}>
          <BookOpen className="mx-auto mb-2 size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            {demo
              ? "The shared demo does not expose workspace wiki entries."
              : "No entries yet. Add your first piece of curated context - deploy policies, team conventions, product definitions."}
          </p>
        </div>
      ) : (
        <div className="grid gap-2">
          {published.map((e) => (
            <div key={e.id} className="card" style={{ padding: "12px 16px" }}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-semibold">{e.title}</div>
                  <p className="mt-1 whitespace-pre-wrap text-sm">{e.content}</p>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {e.updated_by ? `Updated by ${e.updated_by}` : ORIGIN_LABEL[e.origin]}
                  </div>
                </div>
                <div className="flex flex-wrap shrink-0 gap-1.5">
                  <Button size="sm" variant="ghost" onClick={() => startEdit(e)} aria-label={`Edit wiki entry: ${e.title}`}>
                    Edit
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => void showRevisions(e.id)} aria-label={`View revision history for ${e.title}`} disabled={revisionsLoading && revisionsFor === e.id}>
                    <History className="size-3.5" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-destructive"
                    aria-label={`Delete ${e.title}`}
                    onClick={() => { setMutationError(""); setPendingDelete(e); }}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              </div>
              {revisionsFor === e.id && (
                <div className="mt-2 border-t border-[var(--border)] pt-2">
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Revision history
                  </p>
                  {revisionsLoading ? (
                    <p className="text-xs text-muted-foreground" role="status">Loading revision history…</p>
                  ) : revisionsError ? (
                    <div role="alert">
                      <p className="error-text mb-2">{revisionsError}</p>
                      <button type="button" className="btn btn-sm" onClick={() => void showRevisions(e.id)}>Retry</button>
                    </div>
                  ) : revisions.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No earlier versions.</p>
                  ) : (
                    <ul className="space-y-1 text-xs">
                      {revisions.map((r) => (
                        <li key={r.id} className="rounded border border-[var(--border)] px-2 py-1.5">
                          <span className="text-muted-foreground">
                            {r.created_at ? new Date(r.created_at).toLocaleString() : ""}
                            {r.author ? ` · ${r.author}` : ""}
                          </span>
                          <p className="mt-0.5 whitespace-pre-wrap">{r.content}</p>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {pendingDelete && (
        <Dialog open onOpenChange={(open) => !open && !deleteBusy && setPendingDelete(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{pendingDelete.status === "suggested" ? "Dismiss this suggestion?" : "Delete this wiki entry?"}</DialogTitle>
              <DialogDescription>“{pendingDelete.title}” will be permanently removed from the workspace wiki.</DialogDescription>
            </DialogHeader>
            {mutationError && <p className="error-text" role="alert">{mutationError}</p>}
            <DialogFooter>
              <button type="button" className="btn" onClick={() => setPendingDelete(null)} disabled={deleteBusy}>Cancel</button>
              <button type="button" className="btn btn-danger" onClick={() => remove(pendingDelete.id)} disabled={deleteBusy}>
                {deleteBusy ? "Removingâ€¦" : pendingDelete.status === "suggested" ? "Dismiss suggestion" : "Delete entry"}
              </button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
