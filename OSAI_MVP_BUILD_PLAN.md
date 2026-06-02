# OSAI MVP Build Plan

Updated: 2026-06-02

This is the living build plan for the OSAI MVP. Keep this file current as implementation decisions change. The DOCX execution plan is useful for sharing, but this Markdown file should be treated as the working source of truth during the build.

## 1. Build Thesis

OSAI should ship as a connector-first operating layer for scattered company context and execution.

The MVP must prove four things quickly:

- Communication can be unified across Slack, WhatsApp, and Email.
- Knowledge can be searched across Google Drive, Microsoft Office/OneDrive/SharePoint, Notion, Freshdesk, and AI/tool context.
- Work can be converted into clear tasks, tickets, and dashboard state.
- Sensitive company context can be routed through the right model/provider path with auditability.

The goal is not to build a giant marketplace. The goal is to ship a reliable pilot that connects the first few painful systems, retrieves trusted context with citations, and executes visible actions.

## 2. MVP Scope

### Must Ship

- Internal dashboard for connector status, sync runs, workflow runs, extracted actions, and errors.
- Connector registry with a shared interface for all integrations.
- Permission-aware ingestion and retrieval pipeline.
- Natural-language search over connected company data with citations.
- One strong execution workflow: meeting notes/transcripts or pasted context -> action items -> Notion tasks, support updates, or engineering tickets.
- Basic data-tier routing: Normal, Amber, Red.
- Audit events for connector syncs, LLM calls, and actions.

### Should Ship If Fast

- Slack summary posting after workflow runs.
- Freshdesk ticket summarization and suggested next actions.
- Keka read-only employee/leave/policy lookup.
- TallyPrime read-only finance lookup or reporting proof of concept.
- Cursor/Codex/Claude context bridge through MCP.

### Not MVP

- Universal connector marketplace.
- Custom workflow builder.
- Advanced RBAC.
- SAML/SSO.
- Mobile app.
- Full enterprise knowledge graph.
- Self-hosted Whisper unless API cost becomes painful.
- Kubernetes or complex infrastructure.

## 3. Product Surfaces

### Dashboard

The dashboard is the pilot control room.

Required pages:

- `/integrations`: connected tools, auth state, scopes, last sync, sync error.
- `/sync-runs`: recent ingestion jobs and failures.
- `/search`: ask questions across company context with source citations.
- `/workflows`: workflow run log.
- `/workflows/:id`: extracted items, created tasks/tickets, failures, model used.
- `/settings/data-routing`: org data tier config and local model setting.

### Search

Search must return:

- Answer.
- Source citations.
- Source tool.
- Source record title.
- Timestamp or last updated date.
- Confidence or “not enough context” state.

Rule: no citation, no confident answer.

### Workflow

First workflow:

1. User pastes meeting notes/transcript or a transcript arrives from the ingestion pipeline.
2. OSAI enriches context from connected tools.
3. LLM extracts action items into strict JSON.
4. Pydantic validates the output.
5. OSAI creates Notion tasks, Linear/GitHub issues, or Freshdesk follow-ups depending on configured destination.
6. OSAI posts/sends a summary if Slack/email is configured.
7. Dashboard records the full run.

## 4. Integration Priority

| Priority | Connector | Purpose | Implementation Path |
|---|---|---|---|
| P0 | Slack | Team communication and workflow summaries | Composio or Slack API |
| P0 | Gmail | Email decisions and client context | Google API or Composio |
| P0 | Outlook / Microsoft 365 | Enterprise email and Office docs | Microsoft Graph |
| P0 | Google Drive | Docs, Sheets, Slides, PDFs | Google Drive API |
| P0 | OneDrive / SharePoint | Microsoft Office knowledge | Microsoft Graph |
| P0 | Notion | Task management and internal docs | Official Notion API |
| P0 | Freshdesk | Customer support tickets and history | Freshdesk API v2 |
| P1 | Keka | HR employee, leave, attendance, policy lookup | Official Keka API |
| P1 | TallyPrime | Finance reports and accounting lookup | Tally XML/HTTP or JSON integration |
| P1 | WhatsApp Business | Informal customer/team communication | Meta WhatsApp Cloud API |
| P1 | Cursor / code context | Engineering context | MCP bridge and repo docs/issues |
| P2 | ChatGPT / Claude context | AI-generated org knowledge | MCP, exports, shared artifacts |

## 5. Updated Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python 3.12 or 3.13, FastAPI, Pydantic v2 | Use `uv` for dependency management |
| Workers | Celery + Redis | Queues: ingest, transcribe, extract, execute, maintenance |
| Frontend | Next.js current stable, Node 24 LTS | App Router; keep UI pragmatic |
| Database | PostgreSQL, likely Supabase for pilot | Source of truth for orgs, connectors, runs, documents, actions |
| Vector DB | Qdrant | Permission-filtered retrieval |
| Object Storage | Supabase Storage or S3-compatible | Raw transcripts, extracted text, file snapshots |
| OAuth / Tools | Composio first, direct APIs second | Do not build OAuth from scratch unless required |
| Model Gateway | LiteLLM or internal provider adapter | Avoid hardcoding model names in business logic |
| Transcription | OpenAI audio transcription / Whisper path | API first; self-host later if volume demands it |
| Observability | Structured logs, Sentry/OpenTelemetry if fast | Every run needs traceability |
| Deployment | Docker Compose for pilot | Avoid Kubernetes for MVP |

## 6. Repo and File Structure

Recommended backend structure:

```text
osai-backend/
  api/
    main.py
    routes/
      health.py
      integrations.py
      search.py
      sync_runs.py
      workflows.py
      webhooks.py
    schemas/
      action_item.py
      connector.py
      document.py
      workflow_run.py
  workers/
    celery_app.py
    tasks/
      ingest.py
      transcribe.py
      embed.py
      extract.py
      execute.py
  connectors/
    base.py
    registry.py
    slack.py
    gmail.py
    microsoft.py
    google_drive.py
    notion.py
    freshdesk.py
    keka.py
    tally.py
    whatsapp.py
  memory/
    chunker.py
    embeddings.py
    qdrant_store.py
    retriever.py
  workflows/
    action_item_extractor.py
    runner.py
  llm/
    router.py
    prompts/
      action_item_extraction.md
  db/
    models.py
    migrations/
  config.py
  docker-compose.yml
```

Recommended frontend structure:

```text
osai-web/
  app/
    integrations/
    search/
    sync-runs/
    workflows/
      [id]/
    settings/
      data-routing/
  components/
    connector-card.tsx
    source-citation.tsx
    workflow-status.tsx
  lib/
    api.ts
    types.ts
```

## 7. Connector Contract

All connectors should follow the same interface.

```python
class Connector:
    key: str
    display_name: str
    capabilities: set[str]

    async def auth_status(self, org_id: str) -> AuthStatus:
        ...

    async def sync(self, org_id: str, cursor: str | None = None) -> SyncResult:
        ...

    async def get_permissions(self, document: SourceDocument) -> PermissionSet:
        ...

    async def search(self, org_id: str, query: str) -> list[SourceDocument]:
        ...

    async def execute_action(self, org_id: str, action: ConnectorAction) -> ActionResult:
        ...

    async def healthcheck(self, org_id: str) -> HealthcheckResult:
        ...
```

Required normalized object:

```python
class SourceDocument(BaseModel):
    source_id: str
    source_type: str
    org_id: str
    external_id: str
    title: str
    url: str | None = None
    author: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    text: str
    metadata: dict[str, Any] = {}
    permissions: list[str] = []
    data_tier: Literal["normal", "amber", "red"] = "normal"
```

## 8. Data Model

Core tables:

- `orgs`
- `users`
- `connectors`
- `connector_accounts`
- `sync_runs`
- `source_documents`
- `chunks`
- `workflow_runs`
- `action_items`
- `connector_actions`
- `audit_events`
- `model_calls`

Important indexes:

- `source_documents(org_id, source_type, updated_at)`
- `chunks(org_id, source_type, source_document_id)`
- `workflow_runs(org_id, created_at)`
- `audit_events(org_id, created_at, event_type)`
- `connector_accounts(org_id, connector_key)`

## 9. Memory and Retrieval

Chunking rules:

- Prefer 500-1200 token chunks.
- Keep source title and parent metadata on every chunk.
- Preserve links back to original source.
- Store a short `content_preview`.
- Track `source_updated_at`.
- Track `data_tier`.
- Track `permissions`.

Retrieval rules:

- Always filter by `org_id`.
- Apply permissions before the model call.
- Apply data-tier rules before the model call.
- Return citations with the answer.
- If context is weak, return “I do not have enough connected context yet.”

## 10. Model Routing

No workflow should call model providers directly. Use a model router.

Example routing:

| Use case | Primary | Fallback | Validation |
|---|---|---|---|
| Action extraction | Strong reasoning/extraction model | Alternate strong provider | Strict Pydantic schema |
| Search answer synthesis | Strong general model | Cheaper mini model | Citations required |
| Classification | Cheap/fast model | Local model | Enum outputs |
| Red-tier data | Local model | No cloud fallback unless explicitly enabled | Audit event required |

Store on every model call:

- provider
- model
- prompt version
- schema version
- token usage if available
- latency
- data tier
- trace ID

## 11. Open-Source Reuse Strategy

| Project | Use Level | Notes |
|---|---|---|
| `onyx-dot-app/onyx` | Reference/pattern reuse | Connector architecture, permission-aware RAG, metadata schema |
| `ComposioHQ/composio` | Direct dependency | OAuth/tool execution where supported |
| `qdrant/qdrant` | Direct dependency | Vector search and payload filters |
| `BerriAI/litellm` | Direct dependency or adapter reference | Pin versions and monitor security advisories |
| `openai/whisper` | Future self-host fallback | API first for speed |
| `tinyhumansai/openhuman` | Reference only | GPL-3.0; do not copy into closed SaaS code |
| `agiresearch/AIOS` | Reference only | Future scheduling/orchestration ideas |
| `celery/celery` | Direct dependency | Async job execution |

Rule: clone or inspect OSS repos when it saves time, but do not blindly fork large codebases into the product. Reuse patterns, APIs, and small compatible components.

## 12. Fourteen-Day Pilot Build Plan

### Phase 0: Foundation, Day 1

- Create backend scaffold.
- Create frontend scaffold.
- Add Docker Compose with FastAPI, Postgres, Redis, Qdrant.
- Add health endpoint.
- Add basic CI commands: format, lint, typecheck, test.

Exit criteria:

- Local stack boots.
- `/health` reports service status.
- DB migrations run.

### Phase 1: Core Schema, Day 2

- Add org/user tables.
- Add connector registry tables.
- Add sync run, document, chunk, workflow, action, audit tables.
- Seed one pilot org and admin user.

Exit criteria:

- Can create connector records.
- Can record audit event.
- Can create workflow run.

### Phase 2: First Connectors, Days 3-4

Build in this order:

1. Notion
2. Slack
3. Freshdesk
4. Google Drive or Microsoft Graph depending on pilot access

Exit criteria:

- At least three connectors show connected/available state.
- One connector can sync real data.
- One connector can execute an action.

### Phase 3: Ingestion and Retrieval, Days 5-7

- Normalize documents.
- Chunk documents.
- Generate embeddings.
- Write chunks to Qdrant.
- Build retrieval endpoint.
- Build citation object.

Exit criteria:

- Search returns cited results from at least two sources.
- Permission and org filters are applied.

### Phase 4: Workflow Engine, Days 8-10

- Build action-item extraction workflow.
- Add prompt and schema versioning.
- Validate JSON output with Pydantic.
- Create tasks/tickets through connector action.
- Record model calls and connector actions.

Exit criteria:

- Meeting notes create valid action items.
- At least one real downstream task/ticket is created.
- Failures are visible in workflow detail.

### Phase 5: Dashboard, Days 11-12

- Integrations page.
- Sync runs page.
- Search page.
- Workflow runs page.
- Workflow detail page.

Exit criteria:

- Pilot user can understand what happened without reading logs.

### Phase 6: Hardening, Days 13-14

- Add retries.
- Add dead-letter queue handling.
- Add expired credential state.
- Add rate-limit handling.
- Add model fallback.
- Add demo seed data.
- Run end-to-end pilot rehearsal.

Exit criteria:

- Demo is repeatable.
- Known failure modes are visible.
- Pilot credentials are documented.

## 13. Immediate Sprint Backlog

- [x] Create backend repo scaffold.
- [x] Create frontend repo scaffold.
- [x] Add Docker Compose.
- [x] Add Postgres migrations.
- [x] Add connector base interface.
- [x] Add connector registry.
- [ ] Implement Notion connector.
- [ ] Implement Slack connector.
- [ ] Implement Freshdesk connector.
- [ ] Implement one docs connector: Google Drive or Microsoft Graph.
- [x] Implement chunker.
- [ ] Implement embedding pipeline.
- [x] Implement Qdrant store.
- [x] Implement retrieval API.
- [x] Implement citation UI.
- [x] Implement action-item extraction prompt.
- [x] Implement workflow runner.
- [ ] Implement task/ticket execution.
- [x] Implement dashboard pages.
- [ ] Add audit events.
- [x] Add tests for connector contract.
- [x] Add tests for workflow schema validation.

## 14. Acceptance Criteria

The MVP is pilot-ready when:

- At least three real pilot systems are connected.
- Search returns cited answers across connected data.
- One workflow creates real downstream work.
- Dashboard shows syncs, failures, and workflow outputs.
- Permission filters prevent cross-org leakage in tests.
- Every external write action has an audit event.
- Invalid LLM output cannot execute an action.
- The system can be demoed twice in a row without manual DB fixes.

## 15. Known Risks

| Risk | Mitigation |
|---|---|
| Connector sprawl | Keep P0 tight and use shared connector interface |
| OAuth app delays | Use Composio where fast; use API keys for pilot-only direct connectors where acceptable |
| Permission leakage | Filter before model calls; add tests |
| Hallucinated answers | Require citations and uncertainty state |
| Invalid actions | Validate schema and show action preview/log |
| GPL contamination | Treat GPL repos as reference only |
| Keka/Tally API variance | Start read-only and provide CSV/manual fallback if needed |
| Pilot data messiness | Show provenance, sync recency, and source health |

## 16. Build Notes

As implementation progresses, update this section with decisions that differ from the plan.

### Decision Log

- 2026-06-02: MVP direction changed from single Zoom-to-Linear workflow to connector-first operating layer with one polished execution workflow.
- 2026-06-02: Composio remains the preferred acceleration layer, but direct APIs are allowed where Composio does not cover pilot needs well.
- 2026-06-02: OpenHuman is reference-only due to GPL-3.0 licensing concerns.
- 2026-06-02: No existing repo was present in the working folder, so the MVP was scaffolded as a fresh monorepo with `osai-backend`, `osai-web`, and root-level Docker Compose.
- 2026-06-02: Backend scaffold uses FastAPI, Pydantic v2, Celery, Redis, PostgreSQL, Qdrant, and a model-router boundary. Connector implementations are registered as stubs until credentials/API decisions are confirmed.
- 2026-06-02: Frontend scaffold uses Next.js `16.2.7` on Node 24 with App Router pages for integrations, sync runs, search, workflows, workflow detail, and data routing.
- 2026-06-02: `npm audit` still reports two moderate advisories through Next/PostCSS even on current stable `next@16.2.7`; track and upgrade when patched upstream.
- 2026-06-02: Added Alembic and the first core schema migration for orgs, users, connectors, connector accounts, sync runs, source documents, chunks, workflow runs, action items, connector actions, audit events, and model calls.
- 2026-06-02: Added demo seed command for one pilot org, admin user, connector records, connector accounts, and a seed audit event.
- 2026-06-02: API reads now prefer database state for integrations, sync runs, and workflows, with stub fallback when the database is unavailable during early local development.

### Implementation Notes

- Phase 0 first slice landed: API health route, connector registry, shared connector interface, search/workflow route shells, chunker, Qdrant store stub, action extraction prompt, workflow runner stub, Celery queues, dashboard shell, Docker Compose, and initial tests.
- Phase 0/1 schema slice landed: Alembic config, core schema migration, DB session helper, seed helper, and repository reads for dashboard state.
- Verification commands run: `uv run pytest` passed 6 tests, `uv run ruff check .` passed, `npm run typecheck` passed, `docker compose config` rendered successfully, and Alembic upgrade/downgrade passed against a temporary SQLite smoke database.
- Docker Desktop was not running on the workstation, so the actual Compose Postgres migration/seed could not be executed yet. Run `docker compose up -d postgres`, then `uv run alembic upgrade head` and `uv run python -m db.seed` from `osai-backend` once Docker Desktop is available.

### Open Questions

- Which three pilot connectors have confirmed credentials first?
- Should the first execution destination be Notion, Linear/GitHub, or Freshdesk?
- Is WhatsApp Business required for the first pilot demo or can it be P1?
- Does the pilot require Red-tier local model routing immediately?
- Is the internal dashboard being built in an existing Next.js repo or a fresh app?

## 17. Canonical Source Links

- Onyx: https://github.com/onyx-dot-app/onyx
- Onyx connectors: https://docs.onyx.app/admin/connectors
- Composio: https://github.com/ComposioHQ/composio
- Composio docs: https://docs.composio.dev/
- Qdrant: https://github.com/qdrant/qdrant
- Qdrant docs: https://qdrant.tech/documentation/
- OpenAI Whisper: https://github.com/openai/whisper
- OpenAI speech-to-text: https://platform.openai.com/docs/guides/speech-to-text
- LiteLLM: https://docs.litellm.ai/
- Notion API: https://developers.notion.com/
- Freshdesk API: https://developers.freshdesk.com/api/
- Keka API: https://apidocs.keka.com/
- TallyPrime integration: https://help.tallysolutions.com/integration-with-tallyprime/
- WhatsApp Cloud API: https://developers.facebook.com/docs/whatsapp/cloud-api
- Google Drive API: https://developers.google.com/drive/api
- Microsoft Graph: https://learn.microsoft.com/graph/
- Slack API: https://api.slack.com/
