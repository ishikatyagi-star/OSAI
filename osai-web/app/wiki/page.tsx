"use client";

import { useEffect, useState } from "react";
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

const ORIGIN_LABEL: Record<WikiEntry["origin"], string> = {
  manual: "written by hand",
  decision: "from a logged decision",
  correction: "from an answer correction",
};

/** The org wiki ("Context"): curated, versioned knowledge that Ask cites.
 * Suggestions drafted from real work (decisions, corrections) await approval
 * at the top; published entries are editable with full revision history. */
export default function WikiPage() {
  const [entries, setEntries] = useState<WikiEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<WikiEntry | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [revisionsFor, setRevisionsFor] = useState<string | null>(null);
  const [revisions, setRevisions] = useState<WikiRevisionRow[]>([]);

  async function reload() {
    setLoading(true);
    try {
      setEntries(await getWikiEntries());
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
    if (!draftTitle.trim() || !draftContent.trim() || busy) return;
    setBusy(true);
    try {
      if (creating) {
        await createWikiEntry({ title: draftTitle, content: draftContent });
      } else if (editing) {
        await updateWikiEntry(editing.id, { title: draftTitle, content: draftContent });
      }
      cancelEdit();
      await reload();
    } finally {
      setBusy(false);
    }
  }

  async function approve(id: string) {
    await updateWikiEntry(id, { status: "published" });
    reload();
  }

  async function remove(id: string) {
    await deleteWikiEntry(id);
    reload();
  }

  async function showRevisions(id: string) {
    setRevisionsFor(id);
    setRevisions(await getWikiRevisions(id));
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
        <Button onClick={() => startEdit(null)}>
          <Plus size={14} /> New entry
        </Button>
      </div>

      {(creating || editing) && (
        <div className="card" style={{ marginBottom: 16, padding: 16 }}>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-semibold">
              {creating ? "New entry" : `Edit “${editing?.title}”`}
            </span>
            <button type="button" aria-label="Close editor" onClick={cancelEdit}>
              <X className="size-4" />
            </button>
          </div>
          <div className="flex flex-col gap-2">
            <Input
              placeholder="Title"
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
            />
            <Textarea
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
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold">{e.title}</div>
                    <div className="text-xs text-muted-foreground">{ORIGIN_LABEL[e.origin]}</div>
                    <p className="mt-1 whitespace-pre-wrap text-sm">{e.content}</p>
                  </div>
                  <div className="flex shrink-0 gap-1.5">
                    <Button size="sm" onClick={() => approve(e.id)}>
                      <Check className="size-3.5" /> Approve
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => remove(e.id)}>
                      Dismiss
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : published.length === 0 ? (
        <div className="card" style={{ padding: 24, textAlign: "center" }}>
          <BookOpen className="mx-auto mb-2 size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            No entries yet. Add your first piece of curated context - deploy policies,
            team conventions, product definitions.
          </p>
        </div>
      ) : (
        <div className="grid gap-2">
          {published.map((e) => (
            <div key={e.id} className="card" style={{ padding: "12px 16px" }}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-semibold">{e.title}</div>
                  <p className="mt-1 whitespace-pre-wrap text-sm">{e.content}</p>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {e.updated_by ? `Updated by ${e.updated_by}` : ORIGIN_LABEL[e.origin]}
                  </div>
                </div>
                <div className="flex shrink-0 gap-1.5">
                  <Button size="sm" variant="ghost" onClick={() => startEdit(e)}>
                    Edit
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => showRevisions(e.id)}>
                    <History className="size-3.5" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-destructive"
                    aria-label={`Delete ${e.title}`}
                    onClick={() => remove(e.id)}
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
                  {revisions.length === 0 ? (
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
    </div>
  );
}
