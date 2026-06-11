"use client";

import { useEffect, useMemo, useState } from "react";
import { Network, Search, X } from "lucide-react";
import { getGraphEdges, getGraphEntities } from "@/lib/api";
import {
  DEMO_GRAPH_EDGES,
  DEMO_GRAPH_ENTITIES,
} from "@/lib/demo-data";
import { ENTITY_TYPE_META, ENTITY_TYPE_ORDER } from "@/lib/graph-meta";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type {
  GraphEdge,
  GraphEntity,
  GraphEntityType,
} from "@/lib/types";
import { GraphCanvas } from "@/components/graph/graph-canvas";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export default function GraphPage() {
  const [entities, setEntities] = useState<GraphEntity[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [activeTypes, setActiveTypes] = useState<Set<GraphEntityType>>(new Set());
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [usingDemo, setUsingDemo] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [ents, eds] = await Promise.all([
        getGraphEntities(),
        getGraphEdges(),
      ]);
      if (cancelled) return;
      if (ents.length === 0) {
        setEntities(DEMO_GRAPH_ENTITIES);
        setEdges(DEMO_GRAPH_EDGES);
        setUsingDemo(true);
      } else {
        setEntities(ents);
        setEdges(eds);
        setUsingDemo(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function toggleType(t: GraphEntityType) {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  }

  const visibleEntities = useMemo(() => {
    const q = query.trim().toLowerCase();
    return entities.filter((e) => {
      if (activeTypes.size > 0 && !activeTypes.has(e.type)) return false;
      if (q && !`${e.label} ${e.summary ?? ""}`.toLowerCase().includes(q))
        return false;
      return true;
    });
  }, [entities, activeTypes, query]);

  const visibleIds = useMemo(
    () => new Set(visibleEntities.map((e) => e.id)),
    [visibleEntities]
  );

  const visibleEdges = useMemo(
    () =>
      edges.filter(
        (e) => visibleIds.has(e.source_id) && visibleIds.has(e.target_id)
      ),
    [edges, visibleIds]
  );

  const selected = entities.find((e) => e.id === selectedId) ?? null;

  const connections = useMemo(() => {
    if (!selected) return [];
    const out: { entity: GraphEntity; label: string }[] = [];
    for (const e of edges) {
      let otherId: string | null = null;
      if (e.source_id === selected.id) otherId = e.target_id;
      else if (e.target_id === selected.id) otherId = e.source_id;
      if (!otherId) continue;
      const other = entities.find((x) => x.id === otherId);
      if (other) out.push({ entity: other, label: e.label });
    }
    return out;
  }, [selected, edges, entities]);

  return (
    <div className="flex h-[calc(100vh-128px)] flex-col">
      {/* Header */}
      <div className="shrink-0 pb-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2">
              <Network className="size-5 text-primary" />
              Org Graph
            </h1>
            <p className="page-subtitle" style={{ marginBottom: 0 }}>
              Explore people, projects, decisions and tickets, and how they connect across your sources.
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>{visibleEntities.length} entities</span>
            <span className="text-border">·</span>
            <span>{visibleEdges.length} relationships</span>
            {usingDemo && <Badge variant="muted">demo data</Badge>}
          </div>
        </div>

        {/* Filters */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search entities…"
              className="h-8 w-56 pl-8"
            />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {ENTITY_TYPE_ORDER.map((t) => {
              const meta = ENTITY_TYPE_META[t];
              const active = activeTypes.has(t);
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => toggleType(t)}
                  className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium transition-colors"
                  style={{
                    borderColor: active ? meta.color : "var(--border)",
                    background: active ? `${meta.color}22` : "transparent",
                    color: active ? meta.color : "var(--text-secondary)",
                  }}
                >
                  <span
                    className="inline-block size-2 rounded-full"
                    style={{ background: meta.color }}
                  />
                  {meta.label}
                </button>
              );
            })}
            {activeTypes.size > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7"
                onClick={() => setActiveTypes(new Set())}
              >
                Clear
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Canvas + side panel */}
      <div className="flex min-h-0 flex-1 gap-4">
        <div className="min-w-0 flex-1">
          <GraphCanvas
            entities={visibleEntities}
            edges={visibleEdges}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </div>

        {/* Side panel */}
        <aside className="hidden w-80 shrink-0 lg:block">
          {selected ? (
            <div className="flex h-full flex-col overflow-y-auto rounded-lg border border-border bg-card p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <Badge
                    variant="outline"
                    style={{
                      color: ENTITY_TYPE_META[selected.type].color,
                      borderColor: ENTITY_TYPE_META[selected.type].color,
                    }}
                  >
                    {ENTITY_TYPE_META[selected.type].label}
                  </Badge>
                  <h2 className="mt-2 text-base font-semibold text-foreground">
                    {selected.label}
                  </h2>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedId(null)}
                  className="text-muted-foreground hover:text-foreground"
                  aria-label="Close details"
                >
                  <X className="size-4" />
                </button>
              </div>

              {selected.summary && (
                <p className="mt-2 text-sm text-foreground/80">
                  {selected.summary}
                </p>
              )}

              {selected.source_tool && CONNECTOR_META[selected.source_tool] && (
                <div className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span style={{ color: CONNECTOR_META[selected.source_tool].color }}>
                    {CONNECTOR_META[selected.source_tool].icon}
                  </span>
                  Sourced from {CONNECTOR_META[selected.source_tool].label}
                </div>
              )}

              {Object.keys(selected.attributes).length > 0 && (
                <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 rounded-md border border-border bg-background/40 p-2.5 text-xs">
                  {Object.entries(selected.attributes).map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="font-mono text-muted-foreground">{k}</dt>
                      <dd className="truncate text-foreground/80">{v}</dd>
                    </div>
                  ))}
                </dl>
              )}

              <div className="mt-4">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Connections ({connections.length})
                </p>
                <ul className="mt-2 space-y-1.5">
                  {connections.map(({ entity, label }) => (
                    <li key={entity.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(entity.id)}
                        className="flex w-full items-center gap-2 rounded-md border border-border bg-background/40 px-2.5 py-1.5 text-left text-xs transition-colors hover:bg-accent"
                      >
                        <span
                          className="inline-block size-2 shrink-0 rounded-full"
                          style={{ background: ENTITY_TYPE_META[entity.type].color }}
                        />
                        <span className="truncate font-medium text-foreground">
                          {entity.label}
                        </span>
                        <span className="ml-auto shrink-0 font-mono text-muted-foreground">
                          {label}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : (
            <div className="flex h-full flex-col rounded-lg border border-border bg-card p-4">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Legend
              </p>
              <ul className="mt-3 space-y-2">
                {ENTITY_TYPE_ORDER.map((t) => (
                  <li key={t} className="flex items-center gap-2 text-sm">
                    <span
                      className="inline-block size-3 rounded-full"
                      style={{ background: ENTITY_TYPE_META[t].color }}
                    />
                    <span className="text-foreground/80">
                      {ENTITY_TYPE_META[t].label}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-auto pt-4 text-xs text-muted-foreground">
                Click a node to inspect its details and connections. Node size
                reflects how connected an entity is.
              </p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
