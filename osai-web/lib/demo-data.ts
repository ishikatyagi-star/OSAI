// Demo data used as fallback when API is unavailable - makes the product look
// fully populated for recordings and stakeholder demos.

import type { Integration, SyncRun, WorkflowRun, SearchResponse, DataRouting } from "./types";
import type { Department, SavedArtifactRow, TeamMember } from "./api";

export const DEMO_INTEGRATIONS: Integration[] = [
  {
    key: "notion",
    display_name: "Notion",
    capabilities: ["sync", "search", "execute"],
    auth_state: "connected",
    scopes: ["read_content", "read_user"],
    last_sync: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
    sync_error: null,
  },
  {
    key: "slack",
    display_name: "Slack",
    capabilities: ["sync", "search", "execute"],
    auth_state: "connected",
    scopes: ["channels:read", "messages:read"],
    last_sync: new Date(Date.now() - 28 * 60 * 1000).toISOString(),
    sync_error: null,
  },
  {
    key: "google_drive",
    display_name: "Google Drive",
    capabilities: ["sync", "search"],
    auth_state: "connected",
    scopes: ["drive.readonly"],
    last_sync: new Date(Date.now() - 8 * 60 * 60 * 1000).toISOString(),
    sync_error: null,
  },
  {
    key: "freshdesk",
    display_name: "Freshdesk",
    capabilities: ["sync", "search", "execute"],
    auth_state: "connected",
    scopes: ["tickets:read", "agents:read"],
    last_sync: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    sync_error: null,
  },
  {
    key: "zoom",
    display_name: "Zoom",
    capabilities: ["webhook", "transcribe"],
    auth_state: "connected",
    scopes: ["webhook"],
    last_sync: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    sync_error: null,
  },
];

export const DEMO_SYNC_RUNS: SyncRun[] = [
  {
    id: "sync-notion-001",
    connector_key: "notion",
    status: "succeeded",
    started_at: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
    documents_seen: 14,
    documents_indexed: 14,
    error: null,
  },
  {
    id: "sync-slack-002",
    connector_key: "slack",
    status: "succeeded",
    started_at: new Date(Date.now() - 28 * 60 * 1000).toISOString(),
    documents_seen: 112,
    documents_indexed: 110,
    error: null,
  },
  {
    id: "sync-freshdesk-003",
    connector_key: "freshdesk",
    status: "succeeded",
    started_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    documents_seen: 12,
    documents_indexed: 12,
    error: null,
  },
  {
    id: "sync-gdrive-004",
    connector_key: "google_drive",
    status: "succeeded",
    started_at: new Date(Date.now() - 8 * 60 * 60 * 1000).toISOString(),
    documents_seen: 8,
    documents_indexed: 8,
    error: null,
  },
  {
    id: "sync-notion-005",
    connector_key: "notion",
    status: "succeeded",
    started_at: new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString(),
    documents_seen: 5,
    documents_indexed: 5,
    error: null,
  },
  {
    id: "sync-freshdesk-006",
    connector_key: "freshdesk",
    status: "failed",
    started_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
    documents_seen: 0,
    documents_indexed: 0,
    error: "Invalid API credentials - regenerate token in Freshdesk settings",
  },
  {
    id: "sync-slack-007",
    connector_key: "slack",
    status: "succeeded",
    started_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
    documents_seen: 45,
    documents_indexed: 45,
    error: null,
  },
];

export const DEMO_WORKFLOW_RUNS: WorkflowRun[] = [
  {
    id: "workflow-q3-planning",
    kind: "meeting_action_items",
    status: "needs_review",
    destination: "notion",
    model_route: "gemini-2.0-flash",
    created_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
    action_items: [
      {
        id: "item-q3-1",
        title: "Finalise Q3 product roadmap and share with engineering leads",
        owner: "sarah@company.com",
        due_date: "2026-06-13",
        source_quote: "Sarah: I will finalise the Q3 roadmap and share it with the team by next Friday.",
        destination: "notion",
        confidence: 0.97,
        status: "needs_review",
        external_url: null,
        executed_at: null,
      },
      {
        id: "item-q3-2",
        title: "Schedule 5 user interviews for search feature validation",
        owner: "anish@company.com",
        due_date: "2026-06-12",
        source_quote: "Anish: I will set up 5 user interviews before the next sprint.",
        destination: "slack",
        confidence: 0.93,
        status: "needs_review",
        external_url: null,
        executed_at: null,
      },
      {
        id: "item-q3-3",
        title: "Write API documentation for the new webhook endpoint",
        owner: "dev@company.com",
        due_date: "2026-06-10",
        source_quote: "Dev: I will write up the API docs for the Zoom webhook.",
        destination: "notion",
        confidence: 0.91,
        status: "needs_review",
        external_url: null,
        executed_at: null,
      },
    ],
  },
  {
    id: "workflow-sprint-retro",
    kind: "meeting_action_items",
    status: "needs_review",
    destination: "manual",
    model_route: "gemini-2.0-flash",
    created_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    action_items: [
      {
        id: "item-retro-1",
        title: "Clean up sprint board and archive completed tickets",
        owner: "ishika@company.com",
        due_date: "2026-06-12",
        source_quote: "Ishika: I will clean up the sprint board by end of week.",
        destination: "notion",
        confidence: 0.97,
        status: "needs_review",
        external_url: null,
        executed_at: null,
      },
      {
        id: "item-retro-2",
        title: "Run database migration script on staging",
        owner: "sarah@company.com",
        due_date: "2026-06-10",
        source_quote: "Sarah: I will run the database migration before Tuesday's release.",
        destination: "manual",
        confidence: 0.93,
        status: "needs_review",
        external_url: null,
        executed_at: null,
      },
    ],
  },
  {
    id: "workflow-vpc-security",
    kind: "meeting_action_items",
    status: "completed",
    destination: "google_drive",
    model_route: "gemini-2.0-flash",
    created_at: new Date(Date.now() - 18 * 60 * 60 * 1000).toISOString(),
    action_items: [
      {
        id: "item-vpc-1",
        title: "Map VPC security groups for Ollama services",
        owner: "yash@company.com",
        due_date: "2026-06-09",
        source_quote: "Yash: I will map the VPC security groups by Wednesday.",
        destination: "google_drive",
        confidence: 0.89,
        status: "executed",
        external_url: "https://drive.google.com/file/d/vpc-map-123",
        executed_at: new Date(Date.now() - 14 * 60 * 60 * 1000).toISOString(),
      },
    ],
  },
  {
    id: "workflow-security-audit",
    kind: "meeting_action_items",
    status: "completed",
    destination: "freshdesk",
    model_route: "llama3",
    created_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
    action_items: [
      {
        id: "item-sec-1",
        title: "Encrypt all Red-tier databases on local Qdrant",
        owner: "yash@company.com",
        due_date: "2026-06-10",
        source_quote: "Yash: I will encrypt the Red-tier databases by Wednesday.",
        destination: "freshdesk",
        confidence: 0.88,
        status: "executed",
        external_url: "https://freshdesk.com/tickets/101",
        executed_at: new Date(Date.now() - 12 * 60 * 60 * 1000).toISOString(),
      },
    ],
  },
];

export const DEMO_SEARCH_ANSWERS: Record<string, SearchResponse> = {
  default: {
    answer:
      "Based on your synced knowledge base, I found relevant context from Notion, Slack, and Google Drive. The information spans your product roadmap, engineering guidelines, and support protocols. Please try one of the suggested searches below to see a specific answer with citations.",
    citations: [],
    enough_context: true,
  },
  "what are the q3 priorities": {
    answer:
      "Your Q3 priorities centre on three themes:\n\n1. **Search & Retrieval Quality** - improve citation accuracy and reduce hallucination in the RAG pipeline (Notion: Q3 Roadmap doc)\n2. **Connector Coverage** - ship Linear and Confluence connectors, bringing total coverage to 7 sources (Notion: Sprint Backlog)\n3. **Enterprise Readiness** - SSO integration, audit logs export, and SLA-backed uptime targets (Slack: #product-strategy, Jun 4)\n\nAll three are tracked in Notion with owners and weekly check-ins scheduled.",
    citations: [
      {
        source_tool: "notion",
        source_record_title: "Q3 2026 Product Roadmap",
        url: null,
        confidence: 0.96,
      },
      {
        source_tool: "slack",
        source_record_title: "#product-strategy - Jun 4 thread",
        url: null,
        confidence: 0.87,
      },
      {
        source_tool: "notion",
        source_record_title: "Sprint Backlog - June",
        url: null,
        confidence: 0.82,
      },
    ],
    enough_context: true,
  },
  "who is responsible for the vpc security setup": {
    answer:
      "The VPC security setup is owned by **Yash** (yash@company.com). According to the meeting notes from the Security Audit workflow (2 days ago), Yash is responsible for:\n\n- Mapping VPC security groups for Ollama services ✅ Done\n- Encrypting all Red-tier databases on local Qdrant ✅ Done\n- Configuring SSL certificates for the Celery worker\n\nThe task was tracked and auto-pushed to Freshdesk ticket #101. Full documentation is in the VPC and Ollama Security Setup page in Notion.",
    citations: [
      {
        source_tool: "notion",
        source_record_title: "VPC and Ollama Security Setup",
        url: null,
        confidence: 0.95,
      },
      {
        source_tool: "freshdesk",
        source_record_title: "Ticket #101 - VPC Security Encryption",
        url: "https://freshdesk.com/tickets/101",
        confidence: 0.91,
      },
    ],
    enough_context: true,
  },
  "what is the onboarding process for new engineers": {
    answer:
      "New engineer onboarding at your organisation involves four steps according to the Slack #onboarding channel and the Notion Onboarding Guide:\n\n1. **Day 1** - Read the Notion Onboarding Guide, set up local Docker environment (API on port 8000, Qdrant on port 6333)\n2. **Day 1–2** - Connect your Linear and GitHub accounts; get added to relevant Slack channels\n3. **Day 3** - Pair with a senior engineer to walk through the connector architecture\n4. **Week 1** - Ship one small fix or connector improvement to get familiar with the deploy pipeline\n\nThe full guide is maintained in Notion and updated monthly.",
    citations: [
      {
        source_tool: "notion",
        source_record_title: "Sheldon Team Onboarding Guidelines",
        url: null,
        confidence: 0.98,
      },
      {
        source_tool: "slack",
        source_record_title: "#onboarding channel - pinned message",
        url: null,
        confidence: 0.84,
      },
    ],
    enough_context: true,
  },
  "any open sla escalations in freshdesk": {
    answer:
      "There are **2 open SLA escalations** currently tracked in Freshdesk:\n\n1. **Ticket #204** - Enterprise customer \"Meridian Corp\" has a P1 bug affecting API authentication. Opened 3h 42m ago, SLA deadline in 18 minutes. Owner: support@company.com\n2. **Ticket #198** - Connector sync failure on Google Drive for \"Apex Ventures\". Opened 6h ago, within SLA but approaching amber threshold.\n\nBoth tickets are synced into Sheldon and will trigger a Slack alert in #operations if the SLA threshold is breached.",
    citations: [
      {
        source_tool: "freshdesk",
        source_record_title: "Ticket #204 - P1 Auth API Bug (Meridian Corp)",
        url: null,
        confidence: 0.99,
      },
      {
        source_tool: "freshdesk",
        source_record_title: "Ticket #198 - Google Drive Sync Failure (Apex Ventures)",
        url: null,
        confidence: 0.94,
      },
      {
        source_tool: "notion",
        source_record_title: "Freshdesk Integration & SLA Escalation Rules",
        url: null,
        confidence: 0.88,
      },
    ],
    enough_context: true,
  },
};

export const DEMO_DATA_ROUTING: DataRouting = {
  normal: {
    allowed_connectors: ["notion", "slack", "google_drive", "freshdesk"],
    llm_allowed: true,
  },
  amber: {
    allowed_connectors: ["notion", "google_drive"],
    llm_allowed: false,
  },
  red: {
    allowed_connectors: [],
    llm_allowed: false,
  },
};

export const DEMO_DOCS_PER_CONNECTOR: Record<string, number> = {
  notion: 847,
  slack: 302,
  google_drive: 98,
  freshdesk: 47,
  zoom: 12,
};

export const DEMO_DEPARTMENTS: Department[] = [
  { id: "dept-engineering", name: "Engineering", color: "#2563eb", members: 2 },
  { id: "dept-product", name: "Product", color: "#7c3aed", members: 1 },
  { id: "dept-support", name: "Customer Support", color: "#059669", members: 1 },
];

export const DEMO_TEAM_MEMBERS: TeamMember[] = [
  {
    id: "member-sarah",
    email: "sarah@company.com",
    display_name: "Sarah Chen",
    role: "admin",
    department_id: "dept-engineering",
    department: "Engineering",
    data_tier: "red",
    status: "active",
  },
  {
    id: "member-yash",
    email: "yash@company.com",
    display_name: "Yash Das",
    role: "member",
    department_id: "dept-engineering",
    department: "Engineering",
    data_tier: "amber",
    status: "active",
  },
  {
    id: "member-anish",
    email: "anish@company.com",
    display_name: "Anish Patel",
    role: "member",
    department_id: "dept-product",
    department: "Product",
    data_tier: "amber",
    status: "active",
  },
  {
    id: "member-ishika",
    email: "ishika@company.com",
    display_name: "Ishika Tyagi",
    role: "member",
    department_id: "dept-support",
    department: "Customer Support",
    data_tier: "normal",
    status: "active",
  },
];

export const DEMO_STATS = {
  documentsIndexed: Object.values(DEMO_DOCS_PER_CONNECTOR).reduce((sum, count) => sum + count, 0),
  connectorsActive: DEMO_INTEGRATIONS.filter((item) => item.auth_state === "connected").length,
  workflowsRun: 24,
  pendingActions: DEMO_WORKFLOW_RUNS.flatMap((run) => run.action_items ?? []).filter(
    (item) => item.status === "needs_review"
  ).length,
  docsPerConnector: DEMO_DOCS_PER_CONNECTOR,
};

export type Decision = {
  id: string;
  title: string;
  tags: string[];
  status: "proposed" | "approved" | "rejected";
  impact: "critical" | "high" | "medium" | "low";
  owner: string;
  date: string;
  // Where this surfaced from. `identifiedBy: "osai"` marks items Sheldon inferred
  // from context that are NOT tracked in the source tool (the merged Team Board's
  // reason to exist - e.g. the 11th/12th task Notion never listed).
  source: string;
  identifiedBy: "source" | "osai";
};

export const DEMO_DECISIONS: Decision[] = [
  {
    id: "dec-1",
    title: "Adopt Qdrant as primary vector store (replace pgvector)",
    tags: ["architecture", "data"],
    status: "approved",
    impact: "critical",
    owner: "Yash K.",
    date: "Jun 3, 2026",
    source: "Notion",
    identifiedBy: "source",
  },
  {
    id: "dec-2",
    title: "Use Gemini 2.0 Flash as default LLM for action extraction",
    tags: ["ai", "cost"],
    status: "approved",
    impact: "high",
    owner: "Ishika T.",
    date: "Jun 4, 2026",
    source: "Notion",
    identifiedBy: "source",
  },
  {
    id: "dec-3",
    title: "Implement Red/Amber/Normal data routing tiers",
    tags: ["security", "compliance"],
    status: "approved",
    impact: "high",
    owner: "Priya S.",
    date: "Jun 1, 2026",
    source: "Notion",
    identifiedBy: "source",
  },
  {
    id: "dec-4",
    title: "Launch Confluence connector in Q3 (not Q2)",
    tags: ["product", "roadmap"],
    status: "approved",
    impact: "medium",
    owner: "Anish M.",
    date: "Jun 2, 2026",
    source: "Notion",
    identifiedBy: "source",
  },
  {
    id: "dec-5",
    title: "Add SSO / Okta integration before enterprise launch",
    tags: ["auth", "enterprise"],
    status: "proposed",
    impact: "critical",
    owner: "Dev T.",
    date: "Jun 6, 2026",
    source: "Notion",
    identifiedBy: "source",
  },
  {
    id: "dec-6",
    title: "Price Sheldon at $29/seat/month for SMB, $99/seat/month for Enterprise",
    tags: ["pricing", "business"],
    status: "proposed",
    impact: "high",
    owner: "Ishika T.",
    date: "Jun 7, 2026",
    source: "Notion",
    identifiedBy: "source",
  },
  {
    id: "dec-7",
    title: "Deprecate local Ollama model routing for cloud-only inference",
    tags: ["architecture", "cost"],
    status: "rejected",
    impact: "medium",
    owner: "Yash K.",
    date: "May 30, 2026",
    source: "Slack",
    identifiedBy: "source",
  },
  {
    id: "dec-8",
    title: "Build Decision Log as core product feature (dogfood it)",
    tags: ["product"],
    status: "approved",
    impact: "medium",
    owner: "Ishika T.",
    date: "Jun 5, 2026",
    source: "Notion",
    identifiedBy: "source",
  },
  // Sheldon-identified - surfaced from Slack/Freshdesk context but never logged in
  // Notion. These are what the old Team Board existed to highlight.
  {
    id: "dec-9",
    title: "Resolve Redis connection-pool exhaustion before next load test",
    tags: ["infra", "blocker"],
    status: "proposed",
    impact: "critical",
    owner: "Dev T.",
    date: "Jun 12, 2026",
    source: "Slack",
    identifiedBy: "osai",
  },
  {
    id: "dec-10",
    title: "Escalate Freshdesk P1 #FD-2891 - SLA breach risk for Meridian Corp",
    tags: ["support", "sla"],
    status: "proposed",
    impact: "high",
    owner: "Priya S.",
    date: "Jun 8, 2026",
    source: "Freshdesk",
    identifiedBy: "osai",
  },
];

export type BoardTask = {
  id: string;
  title: string;
  priority: "critical" | "high" | "medium" | "low";
  type: "blocker" | "action-item" | "follow-up";
  assignee: string;
  source: string;
  dueDate: string | null;
  column: "pending" | "in_progress" | "done" | "overdue";
};

export const DEMO_BOARD_TASKS: BoardTask[] = [
  { id: "bt-1",  title: "Finalise Q3 roadmap and share with engineering leads",  priority: "high",     type: "action-item", assignee: "Sarah R.",  source: "Notion",    dueDate: "Jun 13",  column: "in_progress" },
  { id: "bt-2",  title: "Schedule 5 user interviews for search validation",       priority: "medium",   type: "action-item", assignee: "Anish M.", source: "Notion",    dueDate: "Jun 12",  column: "in_progress" },
  { id: "bt-3",  title: "Resolve Redis connection pool exhaustion under load",    priority: "critical", type: "blocker",     assignee: "Dev T.",   source: "Slack",     dueDate: "Jun 12",  column: "in_progress" },
  { id: "bt-4",  title: "Fix Freshdesk P1 ticket #FD-2891 (SLA breach risk)",    priority: "critical", type: "blocker",     assignee: "Priya S.", source: "Freshdesk", dueDate: "Jun 8",   column: "overdue" },
  { id: "bt-5",  title: "Write API documentation for new webhook endpoint",       priority: "medium",   type: "action-item", assignee: "Dev T.",   source: "Notion",    dueDate: "Jun 10",  column: "pending" },
  { id: "bt-6",  title: "Encrypt Red-tier databases on Qdrant",                   priority: "high",     type: "action-item", assignee: "Yash K.",  source: "Freshdesk", dueDate: null,      column: "done" },
  { id: "bt-7",  title: "Map VPC security groups for Ollama services",            priority: "high",     type: "action-item", assignee: "Yash K.",  source: "Drive",     dueDate: null,      column: "done" },
  { id: "bt-8",  title: "Clean up sprint board and archive completed tickets",    priority: "low",      type: "action-item", assignee: "Ishika T.", source: "Notion",   dueDate: "Jun 12",  column: "pending" },
  { id: "bt-9",  title: "Send follow-up email to Meridian Corp with Q3 timeline", priority: "high",    type: "follow-up",   assignee: "Anish M.", source: "Zoom",      dueDate: "Jun 9",   column: "overdue" },
  { id: "bt-10", title: "Run database migration script on staging",               priority: "high",     type: "action-item", assignee: "Sarah R.", source: "Notion",    dueDate: "Jun 10",  column: "pending" },
  { id: "bt-11", title: "Prepare competitor positioning slide for board deck",    priority: "medium",   type: "follow-up",   assignee: "Sarah R.", source: "Drive",     dueDate: "Jun 10",  column: "overdue" },
  { id: "bt-12", title: "Deploy Zoom webhook integration to production",          priority: "medium",   type: "action-item", assignee: "Yash K.",  source: "Zoom",      dueDate: null,      column: "done" },
  { id: "bt-13", title: "Finalise investor update deck with KPIs",                priority: "critical", type: "action-item", assignee: "Priya S.", source: "Notion",    dueDate: "Jun 11",  column: "overdue" },
  { id: "bt-14", title: "Set up Okta SSO prototype in staging environment",       priority: "high",     type: "action-item", assignee: "Dev T.",   source: "Notion",    dueDate: "Jun 20",  column: "pending" },
  { id: "bt-15", title: "Conduct security audit on connector credential storage", priority: "critical", type: "blocker",     assignee: "Yash K.",  source: "Notion",    dueDate: "Jun 9",   column: "overdue" },
];


// ─── Ask Sheldon demo answers (fallback for POST /ask) ─────────────────────────────

import type {
  AskResponse,
  GraphEntity,
  GraphEdge,
  EvalRun,
} from "./types";

export const DEMO_ASK_SUGGESTIONS = [
  "What are the Q3 priorities?",
  "Who owns the VPC security setup and is it done?",
  "Summarise open SLA escalations in Freshdesk",
  "Open a Freshdesk ticket for the Redis connection pool issue",
];

export const DEMO_ASK_ANSWERS: Record<string, AskResponse> = {
  default: {
    conversation_id: "conv-demo",
    answer:
      "I can answer questions across everything Sheldon has indexed - Notion, Slack, Google Drive, Freshdesk and Zoom transcripts - and take actions in your connected tools. Try one of the suggested prompts to see a cited answer, and ask me to *open a ticket* or *post to Slack* to see an action-confirmation card.",
    citations: [],
    actions_taken: [],
    enough_context: true,
    via: "osai",
    model_route: "gemini-2.0-flash",
    latency_ms: 120,
  },
  "what are the q3 priorities": {
    conversation_id: "conv-demo",
    answer:
      "Your **Q3 priorities** centre on three themes:\n\n1. **Search & retrieval quality** - improve citation accuracy and reduce hallucination in the RAG pipeline.\n2. **Connector coverage** - ship Linear and Confluence connectors (7 sources total).\n3. **Enterprise readiness** - SSO, audit-log export, and SLA-backed uptime.\n\nAll three are tracked in Notion with owners and weekly check-ins.",
    citations: [
      { source_tool: "notion", source_record_title: "Q3 2026 Product Roadmap", url: null, confidence: 0.96 },
      { source_tool: "slack", source_record_title: "#product-strategy - Jun 4 thread", url: null, confidence: 0.87 },
    ],
    actions_taken: [],
    enough_context: true,
    via: "osai",
    model_route: "gemini-2.0-flash",
    latency_ms: 1840,
  },
  "who owns the vpc security setup and is it done": {
    conversation_id: "conv-demo",
    answer:
      "The VPC security setup is owned by **Yash** (yash@company.com). Per the Security Audit workflow, both tracked tasks are **done**:\n\n- Mapping VPC security groups for Ollama services ✅\n- Encrypting all Red-tier databases on local Qdrant ✅\n\nThe work was auto-pushed to Freshdesk ticket #101.",
    citations: [
      { source_tool: "notion", source_record_title: "VPC and Ollama Security Setup", url: null, confidence: 0.95 },
      { source_tool: "freshdesk", source_record_title: "Ticket #101 - VPC Security Encryption", url: "https://freshdesk.com/tickets/101", confidence: 0.91 },
    ],
    actions_taken: [],
    enough_context: true,
    via: "osai",
    model_route: "gemini-2.0-flash",
    latency_ms: 1610,
  },
  "summarise open sla escalations in freshdesk": {
    conversation_id: "conv-demo",
    answer:
      "There are **2 open SLA escalations** in Freshdesk:\n\n1. **#204** - Meridian Corp, P1 API auth bug. SLA deadline in ~18 min. Owner: support@company.com\n2. **#198** - Apex Ventures, Google Drive sync failure. Within SLA but approaching the amber threshold.\n\nBoth will trigger a Slack alert in #operations if breached.",
    citations: [
      { source_tool: "freshdesk", source_record_title: "Ticket #204 - P1 Auth API Bug (Meridian Corp)", url: null, confidence: 0.99 },
      { source_tool: "freshdesk", source_record_title: "Ticket #198 - Google Drive Sync Failure (Apex Ventures)", url: null, confidence: 0.94 },
    ],
    actions_taken: [],
    enough_context: true,
    via: "osai",
    model_route: "gemini-2.0-flash",
    latency_ms: 1490,
  },
  "open a freshdesk ticket for the redis connection pool issue": {
    conversation_id: "conv-demo",
    answer:
      "I found the issue in Slack #engineering: the **Redis connection pool is exhausting under load** (>500 concurrent tasks), flagged by Dev T. ahead of the June 12 production deploy. I've drafted a Freshdesk ticket - review and approve it below and I'll create it.",
    citations: [
      { source_tool: "slack", source_record_title: "#engineering - Redis pool exhaustion", url: null, confidence: 0.92 },
    ],
    actions_taken: [
      {
        id: "act-redis-1",
        tool: "freshdesk",
        action: "create_ticket",
        summary: "Create a Freshdesk ticket: \"Redis connection pool exhaustion under load\" (priority: high, assignee: Dev T.)",
        status: "proposed",
        requires_confirmation: true,
        params: {
          subject: "Redis connection pool exhaustion under load",
          priority: "high",
          assignee: "dev@company.com",
          description: "Redis connection pool exhausts under >500 concurrent tasks. Needs tuning before the June 12 production deploy.",
        },
        external_url: null,
        error: null,
      },
    ],
    enough_context: true,
    via: "osai",
    model_route: "gemini-2.0-flash",
    latency_ms: 2210,
  },
};

// ─── Org knowledge graph demo (fallback for GET /graph/*) ────────────────────

export const DEMO_GRAPH_ENTITIES: GraphEntity[] = [
  { id: "ent-yash", type: "person", label: "Yash K.", summary: "Engineering - owns infra & security", source_tool: "notion", attributes: { email: "yash@company.com", department: "Engineering" }, degree: 5 },
  { id: "ent-ishika", type: "person", label: "Ishika T.", summary: "Product & backend", source_tool: "notion", attributes: { email: "ishika@company.com", department: "Product" }, degree: 4 },
  { id: "ent-sarah", type: "person", label: "Sarah R.", summary: "Eng lead", source_tool: "slack", attributes: { email: "sarah@company.com", department: "Engineering" }, degree: 3 },
  { id: "ent-anish", type: "person", label: "Anish M.", summary: "Sales / partnerships", source_tool: "zoom", attributes: { email: "anish@company.com", department: "Sales" }, degree: 2 },
  { id: "ent-eng", type: "department", label: "Engineering", summary: "Infra, connectors, RAG pipeline", source_tool: null, attributes: {}, degree: 4 },
  { id: "ent-product", type: "department", label: "Product", summary: "Roadmap & design", source_tool: null, attributes: {}, degree: 3 },
  { id: "ent-vpc", type: "project", label: "VPC Security Setup", summary: "Harden Ollama + Qdrant networking", source_tool: "notion", attributes: { status: "done" }, degree: 3 },
  { id: "ent-q3", type: "project", label: "Q3 Roadmap", summary: "Search quality, connectors, enterprise", source_tool: "notion", attributes: { status: "active" }, degree: 4 },
  { id: "ent-dec-qdrant", type: "decision", label: "Adopt Qdrant as vector store", summary: "Replaces pgvector", source_tool: "notion", attributes: { impact: "critical" }, degree: 2 },
  { id: "ent-dec-sso", type: "decision", label: "Add SSO before enterprise launch", summary: "Okta integration", source_tool: "notion", attributes: { impact: "critical" }, degree: 2 },
  { id: "ent-tkt-204", type: "ticket", label: "Freshdesk #204", summary: "P1 API auth bug - Meridian Corp", source_tool: "freshdesk", attributes: { priority: "P1" }, degree: 2 },
  { id: "ent-tkt-101", type: "ticket", label: "Freshdesk #101", summary: "VPC security encryption", source_tool: "freshdesk", attributes: { priority: "P2" }, degree: 2 },
];

export const DEMO_GRAPH_EDGES: GraphEdge[] = [
  { id: "e1", source_id: "ent-yash", target_id: "ent-eng", type: "works_at", label: "works in", confidence: 0.98, source_tool: "notion" },
  { id: "e2", source_id: "ent-sarah", target_id: "ent-eng", type: "works_at", label: "works in", confidence: 0.97, source_tool: "slack" },
  { id: "e3", source_id: "ent-ishika", target_id: "ent-product", type: "works_at", label: "works in", confidence: 0.96, source_tool: "notion" },
  { id: "e4", source_id: "ent-anish", target_id: "ent-product", type: "works_at", label: "collaborates with", confidence: 0.72, source_tool: "zoom" },
  { id: "e5", source_id: "ent-yash", target_id: "ent-vpc", type: "owns", label: "owns", confidence: 0.95, source_tool: "notion" },
  { id: "e6", source_id: "ent-vpc", target_id: "ent-tkt-101", type: "references", label: "tracked in", confidence: 0.9, source_tool: "freshdesk" },
  { id: "e7", source_id: "ent-ishika", target_id: "ent-q3", type: "owns", label: "owns", confidence: 0.88, source_tool: "notion" },
  { id: "e8", source_id: "ent-q3", target_id: "ent-dec-sso", type: "references", label: "includes", confidence: 0.8, source_tool: "notion" },
  { id: "e9", source_id: "ent-yash", target_id: "ent-dec-qdrant", type: "decided", label: "decided", confidence: 0.85, source_tool: "notion" },
  { id: "e10", source_id: "ent-sarah", target_id: "ent-q3", type: "references", label: "contributes to", confidence: 0.7, source_tool: "slack" },
  { id: "e11", source_id: "ent-anish", target_id: "ent-tkt-204", type: "references", label: "raised", confidence: 0.65, source_tool: "zoom" },
  { id: "e12", source_id: "ent-vpc", target_id: "ent-dec-qdrant", type: "references", label: "depends on", confidence: 0.6, source_tool: "notion" },
];

// ─── Evals demo (fallback for GET /evals) ────────────────────────────────────

export const DEMO_EVAL_RUN: EvalRun = {
  run_id: "eval_2026_06_11",
  created_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
  model_route: "gemini-2.0-flash",
  pass_rate: 0.83,
  total: 18,
  passed: 15,
  failed: 3,
  cases: [
    { id: "own-01", category: "ownership", question: "Who owns the VPC security setup?", expected: "Yash", actual: "Yash K.", passed: true, score: 0.97, latency_ms: 1620, notes: null },
    { id: "own-02", category: "ownership", question: "Who is responsible for the Q3 roadmap?", expected: "Ishika", actual: "Ishika T.", passed: true, score: 0.95, latency_ms: 1490, notes: null },
    { id: "triage-01", category: "ticket_triage", question: "Which open ticket is closest to SLA breach?", expected: "#204", actual: "#204 (Meridian Corp)", passed: true, score: 0.99, latency_ms: 1710, notes: null },
    { id: "triage-02", category: "ticket_triage", question: "What priority should the Redis pool issue be?", expected: "high", actual: "high", passed: true, score: 0.94, latency_ms: 1550, notes: null },
    { id: "route-01", category: "routing", question: "Where should a new product decision be logged?", expected: "Decision Log (Notion)", actual: "Notion Decision Log", passed: true, score: 0.9, latency_ms: 1400, notes: null },
    { id: "route-02", category: "routing", question: "Which channel gets SLA-breach alerts?", expected: "#operations", actual: "#ops", passed: false, score: 0.55, latency_ms: 1380, notes: "Returned an alias, not the canonical channel name." },
    { id: "qa-01", category: "qa", question: "What replaced pgvector?", expected: "Qdrant", actual: "Qdrant", passed: true, score: 0.98, latency_ms: 1320, notes: null },
    { id: "qa-02", category: "qa", question: "What is the onboarding day-1 task?", expected: "Read onboarding guide + set up Docker", actual: "Set up Docker environment", passed: false, score: 0.62, latency_ms: 1600, notes: "Partial - missed the onboarding-guide step." },
    { id: "qa-03", category: "qa", question: "Which connector handles meeting transcripts?", expected: "Zoom", actual: "Zoom", passed: true, score: 0.96, latency_ms: 1280, notes: null },
    { id: "own-03", category: "ownership", question: "Who raised the Meridian Corp escalation?", expected: "Anish", actual: "Unclear from context", passed: false, score: 0.4, latency_ms: 1720, notes: "Low retrieval confidence on the Zoom transcript." },
    { id: "triage-03", category: "ticket_triage", question: "How many open SLA escalations exist?", expected: "2", actual: "2", passed: true, score: 0.93, latency_ms: 1510, notes: null },
    { id: "route-03", category: "routing", question: "Where do meeting action items get pushed?", expected: "Notion / Slack per destination", actual: "Notion or Slack", passed: true, score: 0.88, latency_ms: 1450, notes: null },
    { id: "qa-04", category: "qa", question: "What is the default LLM route?", expected: "gemini-2.0-flash", actual: "Gemini 2.0 Flash", passed: true, score: 0.95, latency_ms: 1300, notes: null },
    { id: "qa-05", category: "qa", question: "What tier blocks LLM access entirely?", expected: "Red", actual: "Red tier", passed: true, score: 0.97, latency_ms: 1250, notes: null },
    { id: "own-04", category: "ownership", question: "Who owns the Redis pool fix?", expected: "Dev", actual: "Dev T.", passed: true, score: 0.92, latency_ms: 1480, notes: null },
    { id: "triage-04", category: "ticket_triage", question: "Is ticket #101 resolved?", expected: "Yes", actual: "Yes - executed", passed: true, score: 0.94, latency_ms: 1390, notes: null },
    { id: "route-04", category: "routing", question: "Which connector is document-retrieval only?", expected: "Qdrant", actual: "Qdrant", passed: true, score: 0.96, latency_ms: 1270, notes: null },
    { id: "qa-06", category: "qa", question: "Name the three data-routing tiers.", expected: "Normal, Amber, Red", actual: "Normal, Amber, Red", passed: true, score: 0.99, latency_ms: 1230, notes: null },
  ],
};

// Pinned artifacts for the demo workspace. The demo has no backend rows to list,
// so without these the Artifacts page reads as broken ("nothing pinned yet") when
// it is really the headline feature: an answer you keep, export and re-ask about.
// Shapes mirror buildOpenUiArtifacts output, one per kind, so the demo shows the
// range (summary metrics, a cited source table, an action plan).
export const DEMO_ARTIFACTS: SavedArtifactRow[] = [
  {
    id: "demo-artifact-sla",
    thread_id: null,
    title: "Open SLA escalations",
    kind: "answer_summary",
    created_by_name: "Admin",
    created_at: "2026-07-13T09:24:00Z",
    data: {
      id: "demo-artifact-sla",
      kind: "answer_summary",
      title: "Open SLA escalations",
      subtitle: "Rolled up from Freshdesk and Slack, refreshed at last sync.",
      metrics: [
        { label: "Open", value: "7", tone: "warning" },
        { label: "Breaching in 4h", value: "2", tone: "danger" },
        { label: "Resolved this week", value: "18", tone: "success" },
      ],
      rows: [
        { label: "Enterprise billing sync failing", value: "Breaching", meta: "Freshdesk #102", tone: "danger" },
        { label: "Redis connection pool errors", value: "4h left", meta: "Freshdesk #98", tone: "warning" },
        { label: "SSO redirect loop", value: "On track", meta: "Freshdesk #91", tone: "neutral" },
      ],
    },
  },
  {
    id: "demo-artifact-vpc",
    thread_id: null,
    title: "Where VPC ownership is documented",
    kind: "source_table",
    created_by_name: "Admin",
    created_at: "2026-07-12T16:05:00Z",
    data: {
      id: "demo-artifact-vpc",
      kind: "source_table",
      title: "Where VPC ownership is documented",
      subtitle: "Every source Sheldon used to answer, with confidence.",
      rows: [
        { label: "VPC and Ollama Security Setup", value: "Notion", meta: "Updated 3 days ago", confidence: 0.94 },
        { label: "Map VPC security groups", value: "Owned by yash@osai.local", meta: "Task", confidence: 0.88 },
        { label: "#infra scoping thread", value: "Slack", meta: "12 replies", confidence: 0.71 },
      ],
    },
  },
  {
    id: "demo-artifact-onboarding",
    thread_id: null,
    title: "Pilot onboarding plan",
    kind: "action_plan",
    created_by_name: "Admin",
    created_at: "2026-07-11T11:40:00Z",
    data: {
      id: "demo-artifact-onboarding",
      kind: "action_plan",
      title: "Pilot onboarding plan",
      subtitle: "Drafted by Sheldon. Every step still needs your approval to run.",
      rows: [
        { label: "Connect Freshdesk and Notion", value: "Done", meta: "Step 1", tone: "success" },
        { label: "Invite the pilot team", value: "In progress", meta: "Step 2", tone: "info" },
        { label: "Schedule the kickoff demo", value: "Needs approval", meta: "Step 3", tone: "warning" },
      ],
    },
  },
];
