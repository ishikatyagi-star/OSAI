# OSAI API Contract

> **Status:** Living document. Per `OSAI_PARALLEL_PLAN.md` §3, the API contract is
> the single shared interface between the backend (Ishika) and frontend (co-founder)
> lanes. Sections marked **✅ Implemented** reflect endpoints already live in
> `osai-backend/`. Sections marked **🟡 Proposed (frontend draft)** were drafted from
> the frontend lane to unblock UI work and **must be ratified/owned by the backend
> lane** before they are considered final — the request/response shapes are what the
> `osai-web/` UI builds against (with mock data shaped identically) until the live
> endpoint lands.

---

## Conventions

- **Base URL:** `NEXT_PUBLIC_API_BASE_URL` (defaults to `http://localhost:8000`).
- **Auth / tenancy:** the frontend sends the current org via the `X-Org-Id` header
  (read from `localStorage.osai_org_id`). Endpoints that also accept `org_id` in the
  body do so for explicitness; the header is authoritative.
- **Content type:** `application/json` for all request bodies.
- **Errors:** non-2xx responses return a text/JSON `detail`. The frontend treats any
  network error or non-2xx on a `GET` as "fall back to demo data."
- **Timestamps:** ISO-8601 strings (UTC).

---

## ✅ Implemented endpoints

These match `osai-web/lib/api.ts` and the live FastAPI routes.

### `POST /auth/login`
Request: `{ "email": string }`
Response: `{ "user_id": string, "org_id": string, "role": string, "token": string }`

### `POST /orgs`
Request: `{ "name": string, "admin_email": string, "admin_display_name": string }`
Response: `{ "org_id": string, "name": string, "admin_email": string, "admin_display_name": string }`

### `GET /integrations`
Response: `Integration[]`
```jsonc
{
  "key": "notion",
  "display_name": "Notion",
  "capabilities": ["sync", "search", "execute"],
  "auth_state": "connected",          // connected | disconnected | error
  "scopes": ["read_content"],
  "last_sync": "2026-06-11T10:15:00Z", // nullable
  "sync_error": null                   // nullable string
}
```

### `POST /integrations/{connectorKey}/sync`
Triggers a sync. Response: arbitrary `{ ... }` ack object.

### `GET /integrations/{connectorKey}/healthcheck`
Response: `{ "healthy": boolean, "message": string }`

### `GET /sync-runs`
Response: `SyncRun[]`
```jsonc
{
  "id": "sync-notion-001",
  "connector_key": "notion",
  "status": "succeeded",              // succeeded | running | failed
  "started_at": "2026-06-11T10:15:00Z",
  "documents_seen": 14,
  "documents_indexed": 14,
  "error": null
}
```

### `POST /search`
Request: `{ "query": string, "org_id": string }`
Response: `SearchResponse`
```jsonc
{
  "answer": "string (may contain **markdown** bold)",
  "citations": [
    {
      "source_tool": "notion",
      "source_record_title": "Q3 2026 Product Roadmap",
      "url": null,                    // nullable
      "confidence": 0.96
    }
  ],
  "enough_context": true
}
```

### `GET /workflows` · `GET /workflows/{id}`
Response: `WorkflowRun` / `WorkflowRun[]`
```jsonc
{
  "id": "workflow-q3-planning",
  "kind": "meeting_action_items",
  "status": "needs_review",           // needs_review | completed | failed
  "destination": "notion",
  "model_route": "gemini-2.0-flash",
  "created_at": "2026-06-11T10:15:00Z",
  "action_items": [
    {
      "id": "item-q3-1",
      "title": "Finalise Q3 roadmap",
      "owner": "sarah@company.com",   // nullable
      "due_date": "2026-06-13",        // nullable
      "source_quote": "Sarah: I will…", // nullable
      "destination": "notion",
      "confidence": 0.97,
      "status": "needs_review",        // needs_review | executed
      "external_url": null,            // nullable
      "executed_at": null              // nullable
    }
  ]
}
```

### `POST /workflows`
Request: `{ "org_id": string, "input_text": string, "destination": string }`
Response: `WorkflowRun`

### `POST /workflows/{runId}/action-items/{itemId}/approve`
Response: `ApproveResult`
```jsonc
{
  "item_id": "item-q3-1",
  "status": "executed",
  "destination": "notion",
  "external_url": "https://notion.so/...", // nullable
  "message": "Created Notion page"
}
```

### `GET /settings/data-routing` · `PATCH /settings/data-routing`
`DataRouting`: per-tier (`normal`/`amber`/`red`) `{ allowed_connectors: string[], llm_allowed: boolean }`.
PATCH request: `{ "routing": DataRouting }`.

---

## 🟡 Proposed (frontend draft — backend to ratify)

### `POST /ask` — the "Ask OSAI" agent  *(Phase 1, P1-T3)*

The conversational agent endpoint. Maps to `agent/orchestrator.py`:
retrieve → tool-calling loop → answer + citations + actions taken.

**Request**
```jsonc
{
  "org_id": "demo-org",
  "question": "Who owns the VPC security setup and is it done?",
  // optional — lets the backend keep multi-turn context (UltraContext, P5).
  "conversation_id": "conv_abc123",      // nullable; server creates one if absent
  // optional — prior turns, if the client wants to send context explicitly.
  "history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

**Response**
```jsonc
{
  "conversation_id": "conv_abc123",
  "answer": "The VPC security setup is owned by **Yash**…",  // markdown
  "citations": [
    {
      "source_tool": "notion",
      "source_record_title": "VPC and Ollama Security Setup",
      "url": null,
      "confidence": 0.95
    }
  ],
  // Actions the agent took or wants to take during this turn.
  "actions_taken": [
    {
      "id": "act_1",
      "tool": "freshdesk",                 // connector / composio toolkit key
      "action": "create_ticket",           // tool action name
      "summary": "Open a Freshdesk ticket for the SLA breach on #204",
      "status": "proposed",                // proposed | executed | failed | skipped
      "requires_confirmation": true,        // true → render an approval card
      "params": { "subject": "SLA breach #204", "priority": "high" },
      "external_url": null,                 // set once executed
      "error": null
    }
  ],
  "enough_context": true,
  // optional debug/telemetry the eval + debug dashboards (P6) can surface.
  "model_route": "gemini-2.0-flash",
  "latency_ms": 1840,
  // optional OpenUI workspace artifacts. The frontend can also derive these
  // from answer + citations + actions_taken when the backend omits them.
  "ui_artifacts": [
    {
      "id": "openui-source-table",
      "kind": "source_table",              // answer_summary | source_table | action_plan | context_gap
      "title": "Source evidence",
      "subtitle": "Citations returned by the OSAI retrieval layer.",
      "metrics": [
        { "label": "Sources", "value": "2", "tone": "success" }
      ],
      "rows": [
        {
          "label": "VPC and Ollama Security Setup",
          "value": "notion",
          "href": null,
          "confidence": 0.95,
          "tone": "success"
        }
      ]
    }
  ]
}
```

### `POST /ask/actions/{actionId}/confirm` — approve a proposed agent action

For `actions_taken[]` items with `requires_confirmation: true`. Mirrors the existing
workflow-approve semantics.

**Request:** `{ "conversation_id": string }`
**Response:**
```jsonc
{
  "id": "act_1",
  "status": "executed",                    // executed | failed
  "external_url": "https://freshdesk.com/tickets/205",
  "message": "Created Freshdesk ticket #205",
  "error": null
}
```

### `GET /graph/entities` — org knowledge graph nodes  *(Phase 4, P4-T4)*

Backed by gbrain. Powers the org graph inspector.

```jsonc
// GET /graph/entities?type=person&q=yash&limit=100
[
  {
    "id": "ent_yash",
    "type": "person",                      // person | project | decision | source | department | ticket
    "label": "Yash K.",
    "summary": "Engineering — owns infra & security",  // nullable
    "source_tool": "notion",               // nullable origin connector
    "attributes": { "email": "yash@company.com", "department": "Engineering" },
    "degree": 7                             // edge count, for sizing in the viz
  }
]
```

### `GET /graph/edges` — org knowledge graph relationships  *(Phase 4, P4-T4)*

```jsonc
// GET /graph/edges?entity_id=ent_yash
[
  {
    "id": "edge_1",
    "source_id": "ent_yash",
    "target_id": "ent_vpc_setup",
    "type": "owns",                        // owns | attended | works_at | references | blocks | decided
    "label": "owns",                       // human-readable
    "confidence": 0.95,
    "source_tool": "notion"                // nullable provenance
  }
]
```

### `GET /evals` — eval run results  *(Phase 6, P6-T2)*

Powers the eval/debug dashboard. Backed by `evals/run_evals.py`.

```jsonc
{
  "run_id": "eval_2026_06_11",
  "created_at": "2026-06-11T09:00:00Z",
  "model_route": "gemini-2.0-flash",
  "pass_rate": 0.82,
  "total": 18,
  "passed": 15,
  "failed": 3,
  "cases": [
    {
      "id": "triage-01",
      "category": "ticket_triage",         // ticket_triage | ownership | routing | qa
      "question": "Who owns the VPC security setup?",
      "expected": "Yash",
      "actual": "Yash K.",
      "passed": true,
      "score": 0.97,
      "latency_ms": 1620,
      "notes": null
    }
  ]
}
```

---

## Changelog

- **2026-06-11** — Initial contract. Documented all implemented endpoints; added
  frontend-drafted proposals for `/ask`, `/ask/actions/{id}/confirm`, `/graph/*`, and
  `/evals` to unblock Phase 1/4/6 UI work. Backend lane to ratify the proposed shapes.
