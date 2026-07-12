"use client";

import { useRef, useState } from "react";
import { Loader2, Paperclip } from "lucide-react";
import { uploadDocuments, type UploadResult } from "@/lib/api";
import { Button } from "@/components/ui/button";
import type { UploadedFile } from "./file-card";

const ACCEPT = ".txt,.md,.markdown,.csv,.log,.pdf,.docx";

/** Paperclip attach for the Ask composer. Files upload immediately with the
 * safe default (visible only to you) — no upfront dialog. Sharing happens
 * afterwards from the file's ⋯ menu (Drive-style "Manage access"). */
export function ComposerAttach({
  onUploaded,
  onError,
  disabled,
}: {
  /** Called with the ingested files after a successful upload. */
  onUploaded: (files: UploadedFile[], skipped: { filename: string; reason: string }[]) => void;
  onError: (message: string) => void;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  async function handleFiles(list: FileList | null) {
    const files = list ? Array.from(list) : [];
    if (!files.length || busy) return;
    setBusy(true);
    try {
      const res: UploadResult = await uploadDocuments(files, { visibility: "personal" });
      if (res.documents_indexed > 0 || res.skipped.length > 0) {
        onUploaded(
          res.documents.map((d) => ({ id: d.id, title: d.title, visibility: res.visibility })),
          res.skipped
        );
      }
      if (res.documents_indexed === 0 && res.skipped.length === 0) {
        onError("Nothing could be ingested from those files.");
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : "";
      onError(
        detail.includes("415") || detail.includes("422")
          ? "Those files couldn't be ingested — supported types: txt, md, csv, log, pdf, docx."
          : "Upload failed — please try again."
      );
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(e) => handleFiles(e.target.files)}
      />
      <Button
        type="button"
        size="icon"
        variant="ghost"
        className="size-9 shrink-0 self-center rounded-full text-[var(--text-muted)]"
        aria-label="Attach files"
        title="Add files to your knowledge base (private to you until shared)"
        disabled={disabled || busy}
        onClick={() => inputRef.current?.click()}
      >
        {busy ? <Loader2 className="size-4 animate-spin" /> : <Paperclip className="size-4" />}
      </Button>
    </>
  );
}
