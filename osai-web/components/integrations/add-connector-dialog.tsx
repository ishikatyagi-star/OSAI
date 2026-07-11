"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Plug, Search } from "lucide-react";
import {
  composioConnect,
  listComposioToolkits,
  type ComposioToolkit,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * Browse-and-connect dialog over the full Composio app catalog.
 *
 * The Integrations page's cards only cover Sheldon AI's native connectors; this
 * dialog exposes everything Composio supports (hundreds of apps) with search
 * and "load more" pagination, so users aren't limited to the default five.
 */
export function AddConnectorDialog({
  open,
  onOpenChange,
  connectedKeys,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  connectedKeys: string[];
}) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<ComposioToolkit[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [error, setError] = useState("");
  // Guards against out-of-order responses while the user is typing.
  const requestSeq = useRef(0);

  async function load(search: string) {
    const seq = ++requestSeq.current;
    setLoading(true);
    setError("");
    const page = await listComposioToolkits(search || undefined);
    if (seq !== requestSeq.current) return; // stale response; a newer search won
    setItems(page.items);
    setCursor(page.next_cursor ?? null);
    setLoading(false);
    if (!page.items.length) {
      setError(
        search
          ? "No apps match that search."
          : "Couldn't load the app catalog. Is Composio configured on the backend?"
      );
    }
  }

  // Initial load + debounced search.
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => load(query), query ? 300 : 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, query]);

  async function loadMore() {
    if (!cursor) return;
    setLoadingMore(true);
    const page = await listComposioToolkits(query || undefined, cursor);
    setItems((prev) => {
      // Dedupe on slug in case pages overlap.
      const seen = new Set(prev.map((t) => t.slug));
      return [...prev, ...page.items.filter((t) => !seen.has(t.slug))];
    });
    setCursor(page.next_cursor ?? null);
    setLoadingMore(false);
  }

  async function handleConnect(slug: string) {
    setConnecting(slug);
    setError("");
    try {
      const res = await composioConnect(slug);
      if (res.redirect_url) {
        // Full-page navigation to the OAuth consent screen (same flow as the
        // native connector cards).
        window.location.href = res.redirect_url;
      } else {
        setError(res.error || "Couldn't start the connection. Try again.");
        setConnecting(null);
      }
    } catch {
      setError("Couldn't start the connection. Try again.");
      setConnecting(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent style={{ maxWidth: 640 }}>
        <DialogHeader>
          <DialogTitle>Add a connector</DialogTitle>
          <DialogDescription>
            Search the full app catalog and connect any tool your team uses.
            Sheldon AI indexes and searches its content; write actions always require
            your approval.
          </DialogDescription>
        </DialogHeader>

        <div style={{ position: "relative", marginBottom: 12 }}>
          <Search
            size={14}
            style={{
              position: "absolute",
              left: 10,
              top: "50%",
              transform: "translateY(-50%)",
              color: "var(--text-secondary)",
            }}
          />
          <Input
            autoFocus
            placeholder="Search apps (Gmail, Jira, HubSpot, GitHub…)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ paddingLeft: 30 }}
            aria-label="Search connector catalog"
          />
        </div>

        {error && (
          <p className="meta" style={{ color: "var(--destructive, var(--red))", marginBottom: 8 }}>
            {error}
          </p>
        )}

        <div style={{ maxHeight: 380, overflowY: "auto", display: "grid", gap: 8 }}>
          {loading ? (
            <div style={{ display: "flex", justifyContent: "center", padding: 24 }}>
              <Loader2 className="animate-spin" size={18} />
            </div>
          ) : (
            items.map((tk) => {
              const isConnected = connectedKeys.includes(tk.slug);
              return (
                <div
                  key={tk.slug}
                  className="card"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "10px 14px",
                  }}
                >
                  {tk.logo ? (
                    // Composio-hosted logo; plain <img> keeps remote domains out
                    // of next.config image allowlists.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={tk.logo}
                      alt=""
                      width={24}
                      height={24}
                      style={{ borderRadius: 6, flexShrink: 0 }}
                    />
                  ) : (
                    <Plug size={18} style={{ flexShrink: 0 }} />
                  )}
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="text-body font-semibold">{tk.name || tk.slug}</div>
                    <div className="meta" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {(tk.categories ?? []).slice(0, 2).map((c) => (
                        <Badge key={c} variant="secondary">
                          {c}
                        </Badge>
                      ))}
                      {typeof tk.tools_count === "number" && (
                        <span>{tk.tools_count} tools</span>
                      )}
                    </div>
                  </div>
                  {isConnected ? (
                    <Badge variant="secondary">Connected</Badge>
                  ) : (
                    <Button
                      size="sm"
                      disabled={connecting !== null}
                      onClick={() => handleConnect(tk.slug)}
                    >
                      {connecting === tk.slug ? (
                        <Loader2 className="animate-spin" size={14} />
                      ) : (
                        "Connect"
                      )}
                    </Button>
                  )}
                </div>
              );
            })
          )}
          {!loading && cursor && (
            <Button variant="outline" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? <Loader2 className="animate-spin" size={14} /> : "Load more"}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
