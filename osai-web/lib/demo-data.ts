// Demo data used as fallback when API is unavailable — makes the product look
// fully populated for recordings and stakeholder demos.

import type { Integration, SyncRun, WorkflowRun, SearchResponse, DataRouting } from "./types";

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
    error: "Invalid API credentials — regenerate token in Freshdesk settings",
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
      "Your Q3 priorities centre on three themes:\n\n1. **Search & Retrieval Quality** — improve citation accuracy and reduce hallucination in the RAG pipeline (Notion: Q3 Roadmap doc)\n2. **Connector Coverage** — ship Linear and Confluence connectors, bringing total coverage to 7 sources (Notion: Sprint Backlog)\n3. **Enterprise Readiness** — SSO integration, audit logs export, and SLA-backed uptime targets (Slack: #product-strategy, Jun 4)\n\nAll three are tracked in Notion with owners and weekly check-ins scheduled.",
    citations: [
      {
        source_tool: "notion",
        source_record_title: "Q3 2026 Product Roadmap",
        url: null,
        confidence: 0.96,
      },
      {
        source_tool: "slack",
        source_record_title: "#product-strategy — Jun 4 thread",
        url: null,
        confidence: 0.87,
      },
      {
        source_tool: "notion",
        source_record_title: "Sprint Backlog — June",
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
        source_record_title: "Ticket #101 — VPC Security Encryption",
        url: "https://freshdesk.com/tickets/101",
        confidence: 0.91,
      },
    ],
    enough_context: true,
  },
  "what is the onboarding process for new engineers": {
    answer:
      "New engineer onboarding at your organisation involves four steps according to the Slack #onboarding channel and the Notion Onboarding Guide:\n\n1. **Day 1** — Read the Notion Onboarding Guide, set up local Docker environment (API on port 8000, Qdrant on port 6333)\n2. **Day 1–2** — Connect your Linear and GitHub accounts; get added to relevant Slack channels\n3. **Day 3** — Pair with a senior engineer to walk through the connector architecture\n4. **Week 1** — Ship one small fix or connector improvement to get familiar with the deploy pipeline\n\nThe full guide is maintained in Notion and updated monthly.",
    citations: [
      {
        source_tool: "notion",
        source_record_title: "OSAI Team Onboarding Guidelines",
        url: null,
        confidence: 0.98,
      },
      {
        source_tool: "slack",
        source_record_title: "#onboarding channel — pinned message",
        url: null,
        confidence: 0.84,
      },
    ],
    enough_context: true,
  },
  "any open sla escalations in freshdesk": {
    answer:
      "There are **2 open SLA escalations** currently tracked in Freshdesk:\n\n1. **Ticket #204** — Enterprise customer \"Meridian Corp\" has a P1 bug affecting API authentication. Opened 3h 42m ago, SLA deadline in 18 minutes. Owner: support@company.com\n2. **Ticket #198** — Connector sync failure on Google Drive for \"Apex Ventures\". Opened 6h ago, within SLA but approaching amber threshold.\n\nBoth tickets are synced into OSAI and will trigger a Slack alert in #operations if the SLA threshold is breached.",
    citations: [
      {
        source_tool: "freshdesk",
        source_record_title: "Ticket #204 — P1 Auth API Bug (Meridian Corp)",
        url: null,
        confidence: 0.99,
      },
      {
        source_tool: "freshdesk",
        source_record_title: "Ticket #198 — Google Drive Sync Failure (Apex Ventures)",
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

export const DEMO_STATS = {
  documentsIndexed: 1247,
  connectorsActive: 5,
  workflowsRun: 24,
  pendingActions: 6,
  docsPerConnector: {
    notion: 847,
    slack: 302,
    google_drive: 98,
    freshdesk: 47,
    zoom: 12,
  } as Record<string, number>,
};

export type InboxItem = {
  id: string;
  type: "blocker" | "follow-up" | "priority" | "update";
  text: string;
  source: string;
  dept: string;
  person: string;
  date: string;
  status: "inbox" | "reviewed";
};

export const DEMO_INBOX_ITEMS: InboxItem[] = [
  {
    id: "inbox-1",
    type: "blocker",
    text: "Engineering is blocked on the Qdrant schema migration. The migration script fails on tables with more than 50k records. No workaround found yet.",
    source: "Notion · Engineering Notes",
    dept: "Engineering",
    person: "Yash K.",
    date: "Jun 8, 2026",
    status: "inbox",
  },
  {
    id: "inbox-2",
    type: "follow-up",
    text: "The Meridian Corp demo went well — they asked for a Confluence connector and SSO by end of Q3. Anish promised a follow-up email with a timeline.",
    source: "Zoom · Partnership Meeting Recording",
    dept: "Sales",
    person: "Anish M.",
    date: "Jun 7, 2026",
    status: "inbox",
  },
  {
    id: "inbox-3",
    type: "priority",
    text: "P1 customer ticket #FD-2891 has been open for 48h without a response. SLA breach in 2h. Needs immediate assignment to a support engineer.",
    source: "Freshdesk · Support Queue",
    dept: "Support",
    person: "Priya S.",
    date: "Jun 7, 2026",
    status: "inbox",
  },
  {
    id: "inbox-4",
    type: "update",
    text: "Q3 product roadmap v2 has been published to the Notion product workspace. Key additions: Confluence connector, Decision Log feature, SSO with Okta.",
    source: "Notion · Product Workspace",
    dept: "Product",
    person: "Ishika T.",
    date: "Jun 6, 2026",
    status: "reviewed",
  },
  {
    id: "inbox-5",
    type: "blocker",
    text: "Redis connection pool exhausting under load testing (>500 concurrent tasks). Needs tuning before production deployment on June 12.",
    source: "Slack · #engineering",
    dept: "Engineering",
    person: "Dev T.",
    date: "Jun 6, 2026",
    status: "inbox",
  },
  {
    id: "inbox-6",
    type: "follow-up",
    text: "Board meeting deck needs to include competitor positioning slide — Glean, Onyx, and Notion AI comparison. Sarah to prepare by June 10.",
    source: "Google Drive · Exec Presentations",
    dept: "Leadership",
    person: "Sarah R.",
    date: "Jun 5, 2026",
    status: "inbox",
  },
  {
    id: "inbox-7",
    type: "update",
    text: "Zoom webhook integration is now live and processing meeting transcripts automatically. First batch of 12 recordings indexed successfully.",
    source: "Zoom · Webhook Events",
    dept: "Engineering",
    person: "Yash K.",
    date: "Jun 5, 2026",
    status: "reviewed",
  },
  {
    id: "inbox-8",
    type: "priority",
    text: "Investor update deck must be finalised by June 11. Key metrics needed: MRR, connector adoption, DAU, and churn rate from last 90 days.",
    source: "Notion · Finance Workspace",
    dept: "Finance",
    person: "Priya S.",
    date: "Jun 4, 2026",
    status: "inbox",
  },
];

export type Decision = {
  id: string;
  title: string;
  tags: string[];
  status: "proposed" | "approved" | "rejected";
  impact: "critical" | "high" | "medium" | "low";
  owner: string;
  date: string;
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
  },
  {
    id: "dec-2",
    title: "Use Gemini 2.0 Flash as default LLM for action extraction",
    tags: ["ai", "cost"],
    status: "approved",
    impact: "high",
    owner: "Ishika T.",
    date: "Jun 4, 2026",
  },
  {
    id: "dec-3",
    title: "Implement Red/Amber/Normal data routing tiers",
    tags: ["security", "compliance"],
    status: "approved",
    impact: "high",
    owner: "Priya S.",
    date: "Jun 1, 2026",
  },
  {
    id: "dec-4",
    title: "Launch Confluence connector in Q3 (not Q2)",
    tags: ["product", "roadmap"],
    status: "approved",
    impact: "medium",
    owner: "Anish M.",
    date: "Jun 2, 2026",
  },
  {
    id: "dec-5",
    title: "Add SSO / Okta integration before enterprise launch",
    tags: ["auth", "enterprise"],
    status: "proposed",
    impact: "critical",
    owner: "Dev T.",
    date: "Jun 6, 2026",
  },
  {
    id: "dec-6",
    title: "Price OSAI at $29/seat/month for SMB, $99/seat/month for Enterprise",
    tags: ["pricing", "business"],
    status: "proposed",
    impact: "high",
    owner: "Ishika T.",
    date: "Jun 7, 2026",
  },
  {
    id: "dec-7",
    title: "Deprecate local Ollama model routing for cloud-only inference",
    tags: ["architecture", "cost"],
    status: "rejected",
    impact: "medium",
    owner: "Yash K.",
    date: "May 30, 2026",
  },
  {
    id: "dec-8",
    title: "Build Decision Log as core product feature (dogfood it)",
    tags: ["product"],
    status: "approved",
    impact: "medium",
    owner: "Ishika T.",
    date: "Jun 5, 2026",
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
