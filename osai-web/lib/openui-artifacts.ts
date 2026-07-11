import {
  openuiLibrary,
  openuiPromptOptions,
} from "@openuidev/react-ui/genui-lib";
import type {
  AskResponse,
  AskUiArtifact,
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

export function buildOpenUiArtifacts(response: AskResponse): AskUiArtifact[] {
  return response.ui_artifacts ?? [];
}
