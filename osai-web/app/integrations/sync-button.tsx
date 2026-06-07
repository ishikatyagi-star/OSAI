"use client";

import { useState } from "react";
import { triggerSync } from "@/lib/api";

export default function SyncButton({ connectorKey }: { connectorKey: string }) {
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [msg, setMsg] = useState("");

  async function handleSync() {
    setState("loading");
    try {
      const result = await triggerSync(connectorKey);
      const docs = result.documents_indexed ?? result.documents_seen ?? 0;
      setMsg(`Synced ${docs} documents`);
      setState("done");
    } catch (e: unknown) {
      setMsg(e instanceof Error ? e.message : "Sync failed");
      setState("error");
    }
    setTimeout(() => setState("idle"), 4000);
  }

  return (
    <div style={{ marginTop: 12 }}>
      <button
        className="btn btn-primary"
        onClick={handleSync}
        disabled={state === "loading"}
        id={`sync-btn-${connectorKey}`}
      >
        {state === "loading" ? "Syncing…" : "Trigger Sync"}
      </button>
      {msg && (
        <span
          style={{ marginLeft: 12, fontSize: 13 }}
          className={state === "error" ? "error-text" : "success-text"}
        >
          {msg}
        </span>
      )}
    </div>
  );
}
