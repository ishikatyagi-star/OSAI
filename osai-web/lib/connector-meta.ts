export type ConnectorMeta = {
  label: string;
  icon: string;
  color: string;
  description: string;
};

export const CONNECTOR_META: Record<string, ConnectorMeta> = {
  notion: {
    label: "Notion",
    icon: "📝",
    color: "#e2e8f0",
    description: "Sync pages, databases, and meeting notes from your Notion workspace.",
  },
  slack: {
    label: "Slack",
    icon: "💬",
    color: "#4ade80",
    description: "Index messages, threads, and pinned content from Slack channels.",
  },
  google_drive: {
    label: "Google Drive",
    icon: "📁",
    color: "#60a5fa",
    description: "Sync Docs, Sheets, and Slides from shared drives and folders.",
  },
  freshdesk: {
    label: "Freshdesk",
    icon: "🎫",
    color: "#fb923c",
    description: "Index support tickets, responses, and agent notes from Freshdesk.",
  },
  zoom: {
    label: "Zoom",
    icon: "📹",
    color: "#c084fc",
    description: "Receive meeting webhooks and auto-transcribe recordings via Whisper.",
  },
  linear: {
    label: "Linear",
    icon: "📐",
    color: "#818cf8",
    description: "Sync issues, projects, and cycles from Linear workspaces.",
  },
  confluence: {
    label: "Confluence",
    icon: "📚",
    color: "#38bdf8",
    description: "Index pages, spaces, and blog posts from Confluence.",
  },
};
