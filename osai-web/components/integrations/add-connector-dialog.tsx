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
      <DialogContent className="connector-catalog-dialog max-w-[760px] gap-0 overflow-hidden p-0">
        <DialogHeader className="connector-catalog-header border-b border-border">
          <DialogTitle className="text-xl">Add a connector</DialogTitle>
          <DialogDescription className="max-w-2xl leading-relaxed">
            Search the full app catalog and connect any tool your team uses.
            Sheldon AI indexes and searches its content; write actions always require
            your approval.
          </DialogDescription>
        </DialogHeader>

        <div className="connector-catalog-search relative">
          <Search
            className="absolute left-9 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            autoFocus
            placeholder="Search apps (Gmail, Jira, HubSpot, GitHub…)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="h-11 rounded-xl pl-10"
            aria-label="Search connector catalog"
          />
        </div>

        {error && (
          <p className="px-6 pb-4 text-sm text-destructive">
            {error}
          </p>
        )}

        <div className="connector-catalog-grid grid max-h-[min(60vh,560px)] grid-cols-1 gap-3 overflow-y-auto border-t border-border bg-muted/20 sm:grid-cols-2">
          {loading ? (
            <div className="col-span-full flex justify-center py-12">
              <Loader2 className="animate-spin" size={18} />
            </div>
          ) : (
            items.map((tk) => {
              const isConnected = connectedKeys.includes(tk.slug);
              return (
                <div
                  key={tk.slug}
                  className="connector-catalog-card flex min-h-[92px] items-center gap-3 rounded-xl border border-border bg-card transition-colors hover:border-border-hover"
                >
                  <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-border bg-background">
                    {tk.logo ? (
                      // Composio-hosted logo; plain <img> keeps remote domains out
                      // of next.config image allowlists.
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={tk.logo}
                        alt=""
                        width={24}
                        height={24}
                        className="rounded-md"
                      />
                    ) : (
                      <Plug className="size-5 text-muted-foreground" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-foreground">
                      {tk.name || tk.slug}
                    </div>
                    <div className="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                      <span className="truncate">
                        {(tk.categories ?? []).slice(0, 2).join(" · ") || "App connector"}
                      </span>
                      {typeof tk.tools_count === "number" && (
                        <span className="shrink-0">· {tk.tools_count} tools</span>
                      )}
                    </div>
                  </div>
                  {isConnected ? (
                    <Badge variant="secondary" className="shrink-0">Connected</Badge>
                  ) : (
                    <Button
                      size="sm"
                      className="min-w-[76px] shrink-0"
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
            <Button className="col-span-full" variant="outline" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? <Loader2 className="animate-spin" size={14} /> : "Load more"}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
