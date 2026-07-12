"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { computeLayout, type LayoutResult } from "@/lib/graph-layout";
import { ENTITY_TYPE_META } from "@/lib/graph-meta";
import type { GraphEdge, GraphEntity } from "@/lib/types";

const WIDTH = 900;
const HEIGHT = 620;

function nodeRadius(degree: number) {
  return 9 + Math.min(degree, 8) * 2.2;
}

export function GraphCanvas({
  entities,
  edges,
  selectedId,
  onSelect,
}: {
  entities: GraphEntity[];
  edges: GraphEdge[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  const [layout, setLayout] = useState<LayoutResult>({});
  const [hoverId, setHoverId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Recompute layout when the graph data changes.
  useEffect(() => {
    setLayout(computeLayout(entities, edges, WIDTH, HEIGHT));
  }, [entities, edges]);

  // Neighbor set for the highlighted (selected or hovered) node.
  const focusId = hoverId ?? selectedId;
  const neighbors = useMemo(() => {
    if (!focusId) return null;
    const set = new Set<string>([focusId]);
    for (const e of edges) {
      if (e.source_id === focusId) set.add(e.target_id);
      if (e.target_id === focusId) set.add(e.source_id);
    }
    return set;
  }, [focusId, edges]);

  const isDimmed = (id: string) => neighbors != null && !neighbors.has(id);

  return (
    <div
      ref={containerRef}
      className="relative h-full w-full overflow-hidden rounded-lg border border-border bg-[#0c0c0c]"
    >
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-full w-full"
        preserveAspectRatio="xMidYMid meet"
        onClick={() => onSelect(null)}
        role="img"
        aria-label="Organisation knowledge graph"
      >
        {/* Edges */}
        <g>
          {edges.map((edge) => {
            const a = layout[edge.source_id];
            const b = layout[edge.target_id];
            if (!a || !b) return null;
            const dim =
              neighbors != null &&
              !(neighbors.has(edge.source_id) && neighbors.has(edge.target_id));
            const active =
              focusId === edge.source_id || focusId === edge.target_id;
            const mx = (a.x + b.x) / 2;
            const my = (a.y + b.y) / 2;
            return (
              <g key={edge.id} opacity={dim ? 0.08 : 1}>
                <line
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke={active ? "var(--text-primary)" : "rgba(41,37,36,0.16)"}
                  strokeWidth={active ? 1.6 : 1}
                />
                {active && (
                  <text
                    x={mx}
                    y={my}
                    dy={-4}
                    textAnchor="middle"
                    className="fill-[var(--text-muted)] text-xs"
                    style={{ fontFamily: "var(--font-mono)" }}
                  >
                    {edge.label}
                  </text>
                )}
              </g>
            );
          })}
        </g>

        {/* Nodes */}
        <g>
          {entities.map((ent) => {
            const p = layout[ent.id];
            if (!p) return null;
            const meta = ENTITY_TYPE_META[ent.type];
            const r = nodeRadius(ent.degree);
            const selected = ent.id === selectedId;
            const dim = isDimmed(ent.id);
            return (
              <g
                key={ent.id}
                transform={`translate(${p.x}, ${p.y})`}
                opacity={dim ? 0.25 : 1}
                style={{ cursor: "pointer", transition: "opacity 120ms" }}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(selected ? null : ent.id);
                }}
                onMouseEnter={() => setHoverId(ent.id)}
                onMouseLeave={() => setHoverId(null)}
              >
                {selected && (
                  <circle r={r + 5} fill="none" stroke={meta.color} strokeWidth={1.5} opacity={0.5} />
                )}
                <circle
                  r={r}
                  fill={meta.color}
                  fillOpacity={selected ? 0.95 : 0.82}
                  stroke="#0c0c0c"
                  strokeWidth={2}
                />
                <text
                  y={r + 13}
                  textAnchor="middle"
                  className="fill-white text-xs"
                  style={{ fontFamily: "var(--font-sans)", pointerEvents: "none" }}
                >
                  {ent.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {entities.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
          No entities match the current filters.
        </div>
      )}
    </div>
  );
}
