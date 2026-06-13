export type ConnectorMeta = {
  label: string;
  icon: string;
  /**
   * Accent hex pulled from the FRAMER palette (see globals.css). Used only for
   * low-prominence single-connector accents (manager modal, a citation icon,
   * graph side panel). Connector lists/grids render neutrally to keep each
   * screen calm — matching the dashboard's Connector Health pattern.
   */
  color: string;
  description: string;
};

export const CONNECTOR_META: Record<string, ConnectorMeta> = {
  notion: {
    label: "Notion",
    icon: "📝",
    color: "#999999",
    description: "Sync pages, databases, and meeting notes from your Notion workspace.",
  },
  slack: {
    label: "Slack",
    icon: "💬",
    color: "#d44df0",
    description: "Index messages, threads, and pinned content from Slack channels.",
  },
  google_drive: {
    label: "Google Drive",
    icon: "📁",
    color: "#0099ff",
    description: "Sync Docs, Sheets, and Slides from shared drives and folders.",
  },
  freshdesk: {
    label: "Freshdesk",
    icon: "🎫",
    color: "#ff7a3d",
    description: "Index support tickets, responses, and agent notes from Freshdesk.",
  },
  zoom: {
    label: "Zoom",
    icon: "📹",
    color: "#6a4cf5",
    description: "Receive meeting webhooks and auto-transcribe recordings via Whisper.",
  },
  linear: {
    label: "Linear",
    icon: "📐",
    color: "#6a4cf5",
    description: "Sync issues, projects, and cycles from Linear workspaces.",
  },
  confluence: {
    label: "Confluence",
    icon: "📚",
    color: "#0099ff",
    description: "Index pages, spaces, and blog posts from Confluence.",
  },
};
