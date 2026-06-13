"use client";

import { useState } from "react";
import { DEMO_BOARD_TASKS, type BoardTask } from "@/lib/demo-data";

type Column = BoardTask["column"];

// Column chrome stays neutral — color is reserved for the one true alert state
// (overdue) and for the priority/type badges on the cards themselves.
const COLUMNS: { id: Column; label: string; accent?: string }[] = [
  { id: "pending",     label: "PENDING" },
  { id: "in_progress", label: "IN PROGRESS" },
  { id: "done",        label: "DONE" },
  { id: "overdue",     label: "OVERDUE", accent: "var(--red)" },
];

const PRIORITY_META: Record<BoardTask["priority"], { cls: string }> = {
  critical: { cls: "badge-red" },
  high:     { cls: "badge-orange" },
  medium:   { cls: "badge-yellow" },
  low:      { cls: "badge-grey" },
};

// Only the transitions that make sense from each column are offered, so a card
// never shows its current state or illogical jumps as an action.
const NEXT_ACTIONS: Record<Column, { label: string; target: Column; primary?: boolean }[]> = {
  pending:     [{ label: "→ In Progress", target: "in_progress" }],
  overdue:     [{ label: "→ In Progress", target: "in_progress" }, { label: "✓ Done", target: "done", primary: true }],
  in_progress: [{ label: "✓ Done", target: "done", primary: true }],
  done:        [{ label: "↩ Reopen", target: "in_progress" }],
};

function TaskCard({ task, onMove }: { task: BoardTask; onMove: (id: string, col: Column) => void }) {
  const actions = NEXT_ACTIONS[task.column];
  return (
    <div
      className="card"
      style={{ padding: "12px 14px", marginBottom: 10, cursor: "grab" }}
    >
      <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
        <span className={`badge ${PRIORITY_META[task.priority].cls}`}>{task.priority}</span>
        <span className={`tag tag-${task.type}`}>{task.type}</span>
      </div>
      <p style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)", margin: "0 0 8px", lineHeight: 1.5 }}>
        {task.title}
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span className="meta" style={{ fontSize: 10 }}>👤 {task.assignee}</span>
        <span className="meta" style={{ fontSize: 10 }}>· {task.source}</span>
        {task.dueDate && (
          <span
            className="meta"
            style={{
              fontSize: 10,
              marginLeft: "auto",
              color: task.column === "overdue" ? "var(--red)" : "var(--text-muted)",
              fontFamily: "var(--font-mono)",
            }}
          >
            {task.dueDate}
          </span>
        )}
      </div>
      {actions.length > 0 && (
        <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
          {actions.map((a) => (
            <button
              key={a.target + a.label}
              className={`btn${a.primary ? " btn-primary" : ""}`}
              style={{ fontSize: 10, padding: "3px 8px" }}
              onClick={() => onMove(task.id, a.target)}
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function BoardPage() {
  const [tasks, setTasks] = useState<BoardTask[]>(DEMO_BOARD_TASKS);

  function moveTask(id: string, col: Column) {
    setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, column: col } : t)));
  }

  const byColumn = (col: Column) => tasks.filter((t) => t.column === col);

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Team Board</h1>
          <p>All extracted tasks and follow-ups in one view. Drag to update status.</p>
        </div>
        <button className="btn btn-primary">+ Add Task</button>
      </div>

      {/* Column counts */}
      <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
        {COLUMNS.map((col) => {
          const count = byColumn(col.id).length;
          const accent = col.accent ?? "var(--text-secondary)";
          return (
            <div
              key={col.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "4px 10px",
                background: "var(--bg-elevated)",
                border: "1px solid var(--border)",
                borderRadius: 6,
                fontSize: 11,
                fontWeight: 700,
                color: count > 0 ? accent : "var(--text-muted)",
              }}
            >
              {col.label}
              <span
                style={{
                  background: "var(--bg-hover)",
                  color: count > 0 ? accent : "var(--text-muted)",
                  borderRadius: "50%",
                  width: 18,
                  height: 18,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 10,
                  fontWeight: 800,
                }}
              >
                {count}
              </span>
            </div>
          );
        })}
      </div>

      {/* Kanban board */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, alignItems: "start" }}>
        {COLUMNS.map((col) => {
          const colTasks = byColumn(col.id);
          return (
            <div key={col.id}>
              {/* Column header */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 12,
                  paddingBottom: 10,
                  borderBottom: "1px solid var(--border)",
                }}
              >
                <span style={{ fontSize: 11, fontWeight: 800, color: col.accent ?? "var(--text-secondary)", letterSpacing: 0.6 }}>
                  {col.label}
                </span>
                <span
                  style={{
                    fontSize: 10,
                    background: "var(--bg-elevated)",
                    color: col.accent ?? "var(--text-secondary)",
                    border: "1px solid var(--border)",
                    borderRadius: 4,
                    padding: "1px 6px",
                    fontWeight: 700,
                  }}
                >
                  {colTasks.length}
                </span>
              </div>

              {/* Tasks */}
              {colTasks.length === 0 && (
                <div
                  style={{
                    border: "1px dashed var(--border)",
                    borderRadius: 8,
                    padding: "24px 16px",
                    textAlign: "center",
                    color: "var(--text-muted)",
                    fontSize: 12,
                  }}
                >
                  No tasks
                </div>
              )}
              {colTasks.map((t) => (
                <TaskCard key={t.id} task={t} onMove={moveTask} />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
