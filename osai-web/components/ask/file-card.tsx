"use client";

import { useEffect, useRef, useState } from "react";
import { Check, FileText, Loader2, MoreVertical } from "lucide-react";
import {
  getTeamMembers,
  updateDocumentAccess,
  type TeamMember,
  type UploadVisibility,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export type UploadedFile = {
  id: string;
  title: string;
  visibility: UploadVisibility;
};

const SCOPE_LABEL: Record<UploadVisibility, string> = {
  personal: "Only you",
  department: "Your department",
  company: "Whole company",
  people: "Specific people",
};

const GENERAL_ACCESS: { id: UploadVisibility; label: string; hint: string }[] = [
  { id: "personal", label: "Only me", hint: "No one else can see or search this file" },
  { id: "department", label: "My department", hint: "Teammates in your department" },
  { id: "company", label: "Whole company", hint: "Everyone in the workspace" },
];

/** An uploaded file in the Ask thread: name + visibility badge + ⋯ menu with a
 * Drive-style "Manage access" dialog (general access + share with people). */
export function FileCard({ file }: { file: UploadedFile }) {
  const [visibility, setVisibility] = useState<UploadVisibility>(file.visibility);
  const [menuOpen, setMenuOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [members, setMembers] = useState<TeamMember[] | null>(null);
  const [sharedWith, setSharedWith] = useState<string[]>([]);
  const [draft, setDraft] = useState<UploadVisibility>(file.visibility);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close the ⋯ menu on outside click.
  useEffect(() => {
    if (!menuOpen) return;
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuOpen]);

  useEffect(() => {
    if (dialogOpen && members === null) {
      getTeamMembers().then(setMembers).catch(() => setMembers([]));
    }
  }, [dialogOpen, members]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const wantsPeople = sharedWith.length > 0;
      const res = await updateDocumentAccess(file.id, {
        visibility: wantsPeople && draft === "personal" ? "people" : draft,
        shared_with: wantsPeople ? sharedWith : undefined,
      });
      setVisibility(res.visibility);
      setSaved(true);
      setTimeout(() => {
        setSaved(false);
        setDialogOpen(false);
      }, 700);
    } catch (err) {
      const detail = err instanceof Error ? err.message : "";
      setError(
        detail.includes("403")
          ? "Only the uploader or an admin can change access."
          : "Couldn't update access — please try again."
      );
    } finally {
      setBusy(false);
    }
  }

  function toggleRecipient(id: string) {
    setSharedWith((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  return (
    <div
      className="card"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 8px 8px 12px",
        maxWidth: 380,
      }}
    >
      <FileText className="size-4 shrink-0 text-[var(--text-muted)]" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{file.title}</div>
        <div className="text-xs text-[var(--text-muted)]">{SCOPE_LABEL[visibility]}</div>
      </div>
      <div ref={menuRef} style={{ position: "relative" }}>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="size-8 rounded-full"
          aria-label={`Options for ${file.title}`}
          onClick={() => setMenuOpen((v) => !v)}
        >
          <MoreVertical className="size-4" />
        </Button>
        {menuOpen && (
          <div
            className="card"
            role="menu"
            style={{
              position: "absolute",
              right: 0,
              top: "calc(100% + 4px)",
              zIndex: 30,
              minWidth: 160,
              padding: 4,
            }}
          >
            <button
              type="button"
              role="menuitem"
              className="w-full rounded px-3 py-2 text-left text-sm hover:bg-[var(--bg-surface)]"
              onClick={() => {
                setMenuOpen(false);
                setDraft(visibility);
                setSharedWith([]);
                setError(null);
                setDialogOpen(true);
              }}
            >
              Manage access
            </button>
          </div>
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Share “{file.title}”</DialogTitle>
            <DialogDescription>
              Choose who can see and ask about this file.
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-[var(--text-muted)]">
                General access
              </span>
              {GENERAL_ACCESS.map((o) => (
                <label
                  key={o.id}
                  className="flex cursor-pointer items-start gap-2 rounded-md border border-[var(--border)] px-3 py-2 text-sm"
                  style={{
                    borderColor: draft === o.id ? "var(--text-primary)" : undefined,
                  }}
                >
                  <input
                    type="radio"
                    name={`access-${file.id}`}
                    checked={draft === o.id}
                    onChange={() => setDraft(o.id)}
                    className="mt-0.5"
                  />
                  <span>
                    <span className="font-medium">{o.label}</span>
                    <span className="block text-xs text-[var(--text-muted)]">{o.hint}</span>
                  </span>
                </label>
              ))}
            </div>

            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-[var(--text-muted)]">
                Share with people
              </span>
              {members === null && (
                <span className="text-xs text-[var(--text-muted)]">Loading teammates…</span>
              )}
              {members?.length === 0 && (
                <span className="text-xs text-[var(--text-muted)]">
                  No teammates yet — invite people from the Team page.
                </span>
              )}
              <div className="flex max-h-36 flex-col gap-1 overflow-y-auto">
                {members?.map((m) => (
                  <label key={m.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={sharedWith.includes(m.id)}
                      onChange={() => toggleRecipient(m.id)}
                    />
                    {m.display_name || m.email}
                    <span className="text-xs text-[var(--text-muted)]">{m.email}</span>
                  </label>
                ))}
              </div>
              <span className="text-xs text-[var(--text-muted)]">
                People you pick are added on top of general access and get notified.
              </span>
            </div>

            {error && <p className="text-xs text-red-500">{error}</p>}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setDialogOpen(false)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button type="button" onClick={save} disabled={busy}>
              {busy ? (
                <Loader2 className="size-4 animate-spin" />
              ) : saved ? (
                <Check className="size-4" />
              ) : (
                "Save"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
