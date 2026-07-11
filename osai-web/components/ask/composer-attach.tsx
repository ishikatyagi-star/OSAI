"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Paperclip, X } from "lucide-react";
import {
  getTeamMembers,
  uploadDocuments,
  type TeamMember,
  type UploadResult,
  type UploadVisibility,
} from "@/lib/api";
import { Button } from "@/components/ui/button";

const ACCEPT = ".txt,.md,.markdown,.csv,.log,.pdf,.docx";

const VISIBILITY_OPTIONS: { id: UploadVisibility; label: string; hint: string }[] = [
  { id: "personal", label: "Only me", hint: "Stays in your account — no one else can see it" },
  { id: "department", label: "My department", hint: "Teammates in your department can see it" },
  { id: "company", label: "Whole company", hint: "Everyone in the workspace can see it" },
  { id: "people", label: "Specific people…", hint: "Pick teammates who can see it" },
];

/** Paperclip attach flow for the Ask composer. Selected files upload into the
 * knowledge base with a "who can see this?" choice (default: only you), then
 * are immediately askable. Visibility maps to permission grants server-side. */
export function ComposerAttach({
  onUploaded,
  disabled,
}: {
  /** Called with a short human note after a successful upload. */
  onUploaded: (note: string) => void;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [visibility, setVisibility] = useState<UploadVisibility>("personal");
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [sharedWith, setSharedWith] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Member list is only needed for "Specific people"; fetch lazily on first use.
  useEffect(() => {
    if (visibility === "people" && members.length === 0) {
      getTeamMembers().then(setMembers).catch(() => setMembers([]));
    }
  }, [visibility, members.length]);

  function reset() {
    setFiles([]);
    setSharedWith([]);
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function upload() {
    if (!files.length || busy) return;
    if (visibility === "people" && sharedWith.length === 0) {
      setError("Pick at least one person.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res: UploadResult = await uploadDocuments(files, {
        visibility,
        sharedWith: visibility === "people" ? sharedWith : undefined,
      });
      const scopeNote =
        visibility === "personal"
          ? "visible only to you"
          : visibility === "department"
            ? "shared with your department"
            : visibility === "company"
              ? "shared with the whole company"
              : `shared with ${sharedWith.length} ${sharedWith.length === 1 ? "person" : "people"}`;
      const parts: string[] = [];
      if (res.documents_indexed > 0) {
        parts.push(
          `Added ${res.documents_indexed} file${res.documents_indexed > 1 ? "s" : ""} to your knowledge base (${scopeNote}). You can ask about ${res.documents_indexed > 1 ? "them" : "it"} right away.`
        );
      }
      for (const s of res.skipped) parts.push(`${s.filename}: ${s.reason}`);
      if (res.documents_indexed > 0) {
        onUploaded(parts.join(" "));
        reset();
      } else {
        setError(parts.join(" ") || "Nothing could be ingested from those files.");
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : "";
      setError(
        detail.includes("415") || detail.includes("422")
          ? "Those files couldn't be ingested — supported types: txt, md, csv, log, pdf, docx."
          : "Upload failed — please try again."
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

  const active = VISIBILITY_OPTIONS.find((o) => o.id === visibility)!;

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(e) => {
          const list = e.target.files;
          if (list?.length) setFiles(Array.from(list));
        }}
      />
      <Button
        type="button"
        size="icon"
        variant="ghost"
        className="size-9 shrink-0 self-center rounded-full text-[var(--text-muted)]"
        aria-label="Attach files"
        title="Attach files to your knowledge base"
        disabled={disabled || busy}
        onClick={() => inputRef.current?.click()}
      >
        <Paperclip className="size-4" />
      </Button>

      {files.length > 0 && (
        <div
          className="card"
          style={{
            position: "absolute",
            bottom: "calc(100% + 8px)",
            left: 0,
            right: 0,
            zIndex: 20,
            padding: "12px 16px",
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex flex-col gap-1 text-sm">
              {files.map((f) => (
                <span key={f.name} className="font-medium">
                  {f.name}
                </span>
              ))}
            </div>
            <button
              type="button"
              aria-label="Cancel attachment"
              onClick={reset}
              className="text-[var(--text-muted)]"
            >
              <X className="size-4" />
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-[var(--text-muted)]">Who can see this?</span>
            {VISIBILITY_OPTIONS.map((o) => (
              <button
                key={o.id}
                type="button"
                onClick={() => setVisibility(o.id)}
                className="btn"
                style={{
                  padding: "4px 10px",
                  borderRadius: 999,
                  border: "1px solid var(--border)",
                  background:
                    visibility === o.id ? "var(--text-primary)" : "transparent",
                  color: visibility === o.id ? "#fff" : "inherit",
                }}
              >
                {o.label}
              </button>
            ))}
          </div>
          <p className="text-xs text-[var(--text-muted)]">{active.hint}</p>

          {visibility === "people" && (
            <div className="flex flex-wrap gap-2 text-xs">
              {members.length === 0 && (
                <span className="text-[var(--text-muted)]">Loading teammates…</span>
              )}
              {members.map((m) => (
                <label key={m.id} className="inline-flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={sharedWith.includes(m.id)}
                    onChange={() => toggleRecipient(m.id)}
                  />
                  {m.display_name || m.email}
                </label>
              ))}
            </div>
          )}

          {error && <p className="text-xs text-red-500">{error}</p>}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={reset} disabled={busy}>
              Cancel
            </Button>
            <Button type="button" size="sm" onClick={upload} disabled={busy}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : "Add to knowledge base"}
            </Button>
          </div>
        </div>
      )}
    </>
  );
}
