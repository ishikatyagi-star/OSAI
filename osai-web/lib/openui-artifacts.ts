import {
  openuiLibrary,
  openuiPromptOptions,
} from "@openuidev/react-ui/genui-lib";
import type {
  AgentAction,
  AskResponse,
  AskUiArtifact,
  AskUiArtifactMetric,
  SourceCitation,
} from "./types";

export const OSAI_OPENUI_PROMPT = openuiLibrary.prompt({
  ...openuiPromptOptions,
  preamble: [
    "You generate compact, trustworthy Sheldon AI workspace artifacts.",
    "Every artifact must preserve citations, confidence, and action approval state.",
    openuiPromptOptions.preamble,
  ]
    .filter(Boolean)
    .join("\n\n"),
  additionalRules: [
    ...(openuiPromptOptions.additionalRules ?? []),
    "Never imply an external action has executed unless the action status is executed.",
    "Prefer compact tables, checklists, and status cards over decorative layouts.",
    "Show missing context as a warning, not as a confident answer.",
  ],
});

function pct(value: number | null | undefined) {
  if (typeof value !== "number" || Number.isNaN(value)) return "n/a";
  return `${Math.round(value * 100)}%`;
}

function averageConfidence(citations: SourceCitation[]) {
  if (!citations.length) return null;
  return citations.reduce((sum, c) => sum + c.confidence, 0) / citations.length;
}

function actionTone(status: AgentAction["status"]): AskUiArtifactMetric["tone"] {
  if (status === "executed") return "success";
  if (status === "failed") return "danger";
  if (status === "skipped") return "neutral";
  return "warning";
}

export function buildOpenUiArtifacts(response: AskResponse): AskUiArtifact[] {
  if (response.ui_artifacts?.length) return response.ui_artifacts;

  const average = averageConfidence(response.citations);
  const proposed = response.actions_taken.filter((a) => a.status === "proposed");
  const executed = response.actions_taken.filter((a) => a.status === "executed");
  const metrics: AskUiArtifactMetric[] = [
    {
      label: "Sources",
      value: response.citations.length.toString(),
      tone: response.citations.length ? "success" : "warning",
    },
    {
      label: "Avg confidence",
      value: pct(average),
      tone: average == null ? "warning" : average >= 0.75 ? "success" : "warning",
    },
    {
      label: "Actions",
      value: response.actions_taken.length.toString(),
      tone: proposed.length ? "warning" : executed.length ? "success" : "neutral",
    },
  ];

  const artifacts: AskUiArtifact[] = [
    {
      id: "openui-answer-summary",
      kind: "answer_summary",
      title: "OpenUI answer workspace",
      subtitle:
        "Structured from the Ask Sheldon AI response without changing the approval flow.",
      metrics,
    },
  ];

  if (response.citations.length) {
    artifacts.push({
      id: "openui-source-table",
      kind: "source_table",
      title: "Source evidence",
      subtitle: "Citations returned by the Sheldon AI retrieval layer.",
      rows: response.citations.map((citation) => ({
        label: citation.source_record_title,
        value: citation.source_tool,
        href: citation.url,
        confidence: citation.confidence,
        tone: citation.confidence >= 0.75 ? "success" : "warning",
      })),
    });
  }

  if (response.actions_taken.length) {
    artifacts.push({
      id: "openui-action-plan",
      kind: "action_plan",
      title: proposed.length ? "Approval queue" : "Action status",
      subtitle: proposed.length
        ? "Actions remain proposed until the user explicitly approves them."
        : "Connector action outcomes from this turn.",
      rows: response.actions_taken.map((action) => ({
        label: action.summary,
        value: `${action.tool} / ${action.action}`,
        meta: action.status,
        href: action.external_url,
        tone: actionTone(action.status),
      })),
    });
  }

  if (!response.enough_context) {
    artifacts.push({
      id: "openui-context-gap",
      kind: "context_gap",
      title: "Context gap",
      subtitle:
        "Sheldon AI did not have enough indexed evidence. Sync relevant connectors before relying on this answer.",
    });
  }

  return artifacts;
}
