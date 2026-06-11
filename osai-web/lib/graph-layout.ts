import type { GraphEdge, GraphEntity } from "./types";

export type NodePosition = { x: number; y: number };
export type LayoutResult = Record<string, NodePosition>;

/**
 * Lightweight, dependency-free force-directed layout (Fruchterman-Reingold
 * style). Deterministic for a given input (seeded initial placement) so the
 * graph doesn't jump around between renders. Runs a fixed number of iterations
 * synchronously — fine for the small org graphs we render.
 */
export function computeLayout(
  entities: GraphEntity[],
  edges: GraphEdge[],
  width: number,
  height: number,
  iterations = 320
): LayoutResult {
  const n = entities.length;
  if (n === 0) return {};

  const area = width * height;
  const k = Math.sqrt(area / n) * 0.8; // ideal edge length
  const center = { x: width / 2, y: height / 2 };

  // Seeded initial placement on a circle (deterministic).
  const pos: Record<string, NodePosition> = {};
  entities.forEach((e, i) => {
    const angle = (i / n) * Math.PI * 2;
    const r = Math.min(width, height) * 0.35;
    pos[e.id] = {
      x: center.x + r * Math.cos(angle),
      y: center.y + r * Math.sin(angle),
    };
  });

  const idIndex = new Set(entities.map((e) => e.id));
  const validEdges = edges.filter(
    (e) => idIndex.has(e.source_id) && idIndex.has(e.target_id)
  );

  let temp = Math.min(width, height) * 0.1;
  const cool = temp / (iterations + 1);

  for (let iter = 0; iter < iterations; iter++) {
    const disp: Record<string, NodePosition> = {};
    for (const e of entities) disp[e.id] = { x: 0, y: 0 };

    // Repulsive forces between every pair.
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = entities[i];
        const b = entities[j];
        let dx = pos[a.id].x - pos[b.id].x;
        let dy = pos[a.id].y - pos[b.id].y;
        let dist = Math.hypot(dx, dy) || 0.01;
        if (dist < 0.01) {
          dx = (Math.random() - 0.5) * 0.1;
          dy = (Math.random() - 0.5) * 0.1;
          dist = Math.hypot(dx, dy) || 0.01;
        }
        const force = (k * k) / dist;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        disp[a.id].x += fx;
        disp[a.id].y += fy;
        disp[b.id].x -= fx;
        disp[b.id].y -= fy;
      }
    }

    // Attractive forces along edges.
    for (const edge of validEdges) {
      const dx = pos[edge.source_id].x - pos[edge.target_id].x;
      const dy = pos[edge.source_id].y - pos[edge.target_id].y;
      const dist = Math.hypot(dx, dy) || 0.01;
      const force = (dist * dist) / k;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      disp[edge.source_id].x -= fx;
      disp[edge.source_id].y -= fy;
      disp[edge.target_id].x += fx;
      disp[edge.target_id].y += fy;
    }

    // Gentle pull toward the center to keep disconnected nodes in frame.
    for (const e of entities) {
      disp[e.id].x += (center.x - pos[e.id].x) * 0.012;
      disp[e.id].y += (center.y - pos[e.id].y) * 0.012;
    }

    // Apply displacement, capped by temperature; clamp to bounds.
    const pad = 48;
    for (const e of entities) {
      const d = disp[e.id];
      const len = Math.hypot(d.x, d.y) || 0.01;
      pos[e.id].x += (d.x / len) * Math.min(len, temp);
      pos[e.id].y += (d.y / len) * Math.min(len, temp);
      pos[e.id].x = Math.max(pad, Math.min(width - pad, pos[e.id].x));
      pos[e.id].y = Math.max(pad, Math.min(height - pad, pos[e.id].y));
    }

    temp = Math.max(temp - cool, 0.01);
  }

  return pos;
}
