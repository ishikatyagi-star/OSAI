"use client";

import { useEffect, useRef, useState } from "react";
import { FileUp, Loader2 } from "lucide-react";
import { getDepartments, uploadDocuments, type Department, type UploadResult } from "@/lib/api";
import { Button } from "@/components/ui/button";

const ACCEPT = ".txt,.md,.markdown,.csv,.log,.pdf,.docx";
type Tier = "normal" | "amber" | "red";

const TIER_HINT: Record<Tier, string> = {
  normal: "Anyone in the org, any model",
  amber: "Restricted cloud model routing",
  red: "Never leaves local models",
};

/** Drag-and-drop / file-picker upload into the knowledge base. Uploaded files
 * go through the same ingestion pipeline as connector syncs (tier rules,
 * chunking, vectors), so they're immediately searchable in Ask. */
export function UploadCard({ onUploaded }: { onUploaded?: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [tier, setTier] = useState<Tier>("normal");
  const [departments, setDepartments] = useState<Department[]>([]);
  const [departmentId, setDepartmentId] = useState<string>("");

  useEffect(() => {
    getDepartments().then(setDepartments).catch(() => setDepartments([]));
  }, []);
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  async function handleFiles(list: FileList | File[]) {
    const files = Array.from(list);
    if (!files.length || busy) return;
    setBusy(true);
    setMessage(null);
    try {
      const res: UploadResult = await uploadDocuments(files, tier, departmentId || undefined);
      const parts: string[] = [];
      if (res.documents_indexed > 0) {
        parts.push(
          `Indexed ${res.documents_indexed} file${res.documents_indexed > 1 ? "s" : ""} - ask about them now.`
        );
      }
      for (const s of res.skipped) parts.push(`${s.filename}: ${s.reason}`);
      if (res.vector_error) parts.push("Search indexing is catching up - results may lag briefly.");
      setMessage({ text: parts.join(" "), ok: res.documents_indexed > 0 });
      if (res.documents_indexed > 0) onUploaded?.();
    } catch (err) {
      const detail = err instanceof Error ? err.message : "";
      setMessage({
        text: detail.includes("415") || detail.includes("422")
          ? "Those files couldn't be ingested - supported types: txt, md, csv, log, pdf, docx."
          : "Upload failed - please try again.",
        ok: false,
      });
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div
      className="card"
      style={{
        marginBottom: 16,
        borderStyle: dragOver ? "dashed" : undefined,
        borderColor: dragOver ? "var(--accent, var(--green))" : undefined,
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        handleFiles(e.dataTransfer.files);
      }}
    >
      <div className="flex flex-wrap items-center gap-3">
        <FileUp size={18} style={{ color: "var(--text-secondary)", flexShrink: 0 }} />
        <div style={{ flex: 1, minWidth: 220 }}>
          <p className="text-body font-semibold" style={{ marginBottom: 2 }}>
            Upload files to your knowledge base
          </p>
          <p className="meta">
            Drop PDF, Word, Markdown, or text files here - they become searchable in Ask
            with the tier you pick.
          </p>
        </div>
        {departments.length > 0 && (
          <label className="meta inline-flex items-center gap-2" style={{ whiteSpace: "nowrap" }}>
            Department
            <select
              value={departmentId}
              onChange={(e) => setDepartmentId(e.target.value)}
              style={{
                background: "var(--surface, transparent)",
                color: "inherit",
                border: "1px solid var(--border, currentColor)",
                borderRadius: 8,
                padding: "4px 8px",
              }}
            >
              <option value="">Whole workspace</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="meta inline-flex items-center gap-2" style={{ whiteSpace: "nowrap" }}>
          Tier
          <select
            value={tier}
            onChange={(e) => setTier(e.target.value as Tier)}
            title={TIER_HINT[tier]}
            style={{
              background: "var(--surface, transparent)",
              color: "inherit",
              border: "1px solid var(--border, currentColor)",
              borderRadius: 8,
              padding: "4px 8px",
            }}
          >
            <option value="normal">Normal</option>
            <option value="amber">Amber</option>
            <option value="red">Red</option>
          </select>
        </label>
        <Button className="min-w-[140px]" onClick={() => inputRef.current?.click()} disabled={busy}>
          {busy ? <Loader2 size={14} className="animate-spin" /> : <FileUp size={14} />}
          {busy ? "Uploading…" : "Upload files"}
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
        />
      </div>
      {message && (
        <p
          className="text-caption"
          style={{
            marginTop: 10,
            fontWeight: 600,
            color: message.ok ? "var(--green)" : "var(--red, #d33)",
          }}
        >
          {message.text}
        </p>
      )}
    </div>
  );
}
