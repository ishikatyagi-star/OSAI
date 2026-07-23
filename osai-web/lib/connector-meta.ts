import {
  BookOpen,
  FolderOpen,
  Mail,
  MessageSquare,
  PenLine,
  Plug,
  Ruler,
  Ticket,
  Video,
  type LucideIcon,
} from "lucide-react";

export type ConnectorMeta = {
  label: string;
  icon: LucideIcon;
  availability: "supported" | "legacy-unavailable";
  /**
   * Accent hex pulled from the FRAMER palette (see globals.css). Used only for
   * low-prominence single-connector accents (manager modal, a citation icon,
   * graph side panel). Connector lists/grids render neutrally to keep each
   * screen calm - matching the dashboard's Connector Health pattern.
   */
  color: string;
  description: string;
};

export const CONNECTOR_META: Record<string, ConnectorMeta> = {
  notion: {
    label: "Notion",
    icon: PenLine,
    availability: "supported",
    color: "#999999",
    description: "Sync pages, databases, and meeting notes from your Notion workspace.",
  },
  slack: {
    label: "Slack",
    icon: MessageSquare,
    availability: "supported",
    color: "#d44df0",
    description: "Index messages, threads, and pinned content from Slack channels.",
  },
  google_drive: {
    label: "Google Drive",
    icon: FolderOpen,
    availability: "supported",
    color: "#0099ff",
    description: "Sync Docs, Sheets, and Slides from shared drives and folders.",
  },
  gmail: {
    label: "Gmail",
    icon: Mail,
    availability: "supported",
    color: "#ea4335",
    description: "Index email messages from the connected Gmail account.",
  },
  freshdesk: {
    label: "Freshdesk",
    icon: Ticket,
    availability: "supported",
    color: "#ff7a3d",
    description: "Index support tickets, responses, and agent notes from Freshdesk.",
  },
  zoom: {
    label: "Zoom",
    icon: Video,
    availability: "legacy-unavailable",
    color: "#6a4cf5",
    description: "Legacy label only. Zoom ingestion, webhooks, and transcription are unavailable.",
  },
  linear: {
    label: "Linear",
    icon: Ruler,
    availability: "legacy-unavailable",
    color: "#6a4cf5",
    description: "Legacy label only. Linear indexing is unavailable in this release.",
  },
  confluence: {
    label: "Confluence",
    icon: BookOpen,
    availability: "legacy-unavailable",
    color: "#0099ff",
    description: "Legacy label only. Confluence indexing is unavailable in this release.",
  },
};

export function getConnectorIcon(key: string): LucideIcon {
  return CONNECTOR_META[key]?.icon ?? Plug;
}
