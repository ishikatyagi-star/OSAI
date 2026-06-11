import type { GraphEntityType } from "./types";

export type EntityTypeMeta = {
  label: string;
  /** Hex color pulled from the OSAI palette. */
  color: string;
  icon: string;
};

export const ENTITY_TYPE_META: Record<GraphEntityType, EntityTypeMeta> = {
  person: { label: "Person", color: "#00c896", icon: "●" },
  project: { label: "Project", color: "#4d9fff", icon: "◆" },
  decision: { label: "Decision", color: "#a855f7", icon: "◇" },
  source: { label: "Source", color: "#888888", icon: "▣" },
  department: { label: "Department", color: "#f5c842", icon: "▰" },
  ticket: { label: "Ticket", color: "#ff8c42", icon: "▲" },
};

export const ENTITY_TYPE_ORDER: GraphEntityType[] = [
  "person",
  "department",
  "project",
  "decision",
  "ticket",
  "source",
];
