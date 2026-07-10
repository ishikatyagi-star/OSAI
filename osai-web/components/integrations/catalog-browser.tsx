"use client";

import { useDeferredValue, useEffect, useState } from "react";
import { Check, FileText, Loader2, Plug, Search } from "lucide-react";
import {
  composioConnect,
  composioDisconnect,
  getComposioToolkitCategories,
  getComposioToolkits,
  type ComposioToolkit,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Category = { id: string; name: string };

export function CatalogBrowser({ onConnectionChange }: { onConnectionChange?: () => void }) {
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [category, setCategory] = useState("");
  const [categories, setCategories] = useState<Category[]>([]);
  const [items, setItems] = useState<ComposioToolkit[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [workingSlug, setWorkingSlug] = useState<string | null>(null);

  useEffect(() => {
    getComposioToolkitCategories().then((page) => setCategories(page.items.slice(0, 8)));
  }, []);

  useEffect(() => {
    let current = true;
    setLoading(true);
    getComposioToolkits({ search: deferredSearch, category: category || undefined })
      .then((page) => {
        if (!current) return;
        setItems(page.items);
        setNextCursor(page.next_cursor);
      })
      .finally(() => current && setLoading(false));
    return () => { current = false; };
  }, [deferredSearch, category]);

  async function loadMore() {
    if (!nextCursor) return;
    setLoadingMore(true);
    try {
      const page = await getComposioToolkits({ search: deferredSearch, category: category || undefined, cursor: nextCursor });
      setItems((current) => [...current, ...page.items]);
      setNextCursor(page.next_cursor);
    } finally {
      setLoadingMore(false);
    }
  }

  async function toggleConnection(item: ComposioToolkit) {
    setWorkingSlug(item.slug);
    try {
      if (item.connected) {
        await composioDisconnect(item.slug);
        setItems((current) => current.map((entry) => entry.slug === item.slug ? { ...entry, connected: false } : entry));
        onConnectionChange?.();
        return;
      }
      const result = await composioConnect(item.slug);
      if (result.redirect_url) window.location.href = result.redirect_url;
    } finally {
      setWorkingSlug(null);
    }
  }

  return (
    <section className="mt-8">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">Browse all connectors</p>
          <p className="mt-1 text-xs text-muted-foreground">Connect any Composio app for agent actions. Sources that sync documents are labeled clearly.</p>
        </div>
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(event) => setSearch(event.target.value)} className="min-h-10 pl-9" placeholder="Search Jira, Salesforce, Calendly..." />
        </div>
      </div>
      <div className="mb-4 flex flex-wrap gap-2">
        <Button variant={category ? "ghost" : "secondary"} size="sm" onClick={() => setCategory("")}>All</Button>
        {categories.map((entry) => (
          <Button key={entry.id} variant={category === entry.id ? "secondary" : "ghost"} size="sm" onClick={() => setCategory(entry.id)}>{entry.name}</Button>
        ))}
      </div>
      {loading ? (
        <div className="flex min-h-32 items-center justify-center text-sm text-muted-foreground"><Loader2 className="mr-2 size-4 animate-spin" />Loading catalog...</div>
      ) : (
        <>
          <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))" }}>
            {items.map((item) => (
              <article key={item.slug} className="card flex flex-col gap-3">
                <div className="flex items-start gap-3">
                  <div className="connector-icon-badge flex shrink-0 items-center justify-center overflow-hidden" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
                    {item.logo ? <img src={item.logo} alt="" className="size-5 object-contain" /> : <Plug className="size-5" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <h3 className="truncate text-sm font-semibold">{item.name || item.slug}</h3>
                    <p className="mt-1 text-xs text-muted-foreground">{item.tools_count ?? 0} agent tools{item.categories.length ? ` · ${item.categories[0]}` : ""}</p>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">
                  {item.connected ? <span className="inline-flex items-center gap-1 text-success"><Check className="size-3.5" />Connected</span> : item.capabilities.sync ? <span className="inline-flex items-center gap-1"><FileText className="size-3.5" />Syncs documents</span> : "Agent actions only - document sync coming for this app."}
                </p>
                <Button size="sm" className="mt-auto h-10" variant={item.connected ? "ghost" : "default"} disabled={workingSlug === item.slug} onClick={() => toggleConnection(item)}>
                  {workingSlug === item.slug ? <Loader2 className="size-3.5 animate-spin" /> : item.connected ? "Disconnect" : "Connect"}
                </Button>
              </article>
            ))}
          </div>
          {items.length === 0 && <p className="py-8 text-center text-sm text-muted-foreground">No connectors matched that search.</p>}
          {nextCursor && <div className="mt-5 text-center"><Button variant="ghost" disabled={loadingMore} onClick={loadMore}>{loadingMore && <Loader2 className="size-3.5 animate-spin" />}Load more</Button></div>}
        </>
      )}
    </section>
  );
}
