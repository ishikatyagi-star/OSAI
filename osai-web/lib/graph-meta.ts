import type { GraphEntityType } from "./types";

export type EntityTypeMeta = {
  label: string;
  /** Hex color pulled from the OSAI palette. */
  color: string;
  icon: string;
};

export const ENTITY_TYPE_META: Record<GraphEntityType, EntityTypeMeta> = {
  person: { label: "Person", color: "#0099ff", icon: "●" },
  project: { label: "Project", color: "#6a4cf5", icon: "◆" },
  decision: { label: "Decision", color: "#d44df0", icon: "◇" },
  source: { label: "Source", color: "#999999", icon: "▣" },
  department: { label: "Department", color: "#f5c842", icon: "▰" },
  ticket: { label: "Ticket", color: "#ff7a3d", icon: "▲" },
};

export const ENTITY_TYPE_ORDER: GraphEntityType[] = [
  "person",
  "department",
  "project",
  "decision",
  "ticket",
  "source",
];
