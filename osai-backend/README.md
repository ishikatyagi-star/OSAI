# OSAI Backend

```powershell
uv sync
uv run pytest
uv run alembic upgrade head
uv run python -m db.seed
uv run uvicorn api.main:app --reload --no-proxy-headers --host 0.0.0.0 --port 8000
```

Notion direct API sync uses `OSAI_NOTION_API_TOKEN`. Optionally set
`OSAI_NOTION_ROOT_PAGE_ID` to sync a specific page subtree; otherwise the connector searches
the integration-visible workspace.

## High-cost request limits

Production uses the shared Redis limiter and fails closed with `503` when Redis
cannot enforce a budget. Local and test runs use the bounded memory backend.
Every counter is isolated by verified tenant, client, and route; signed OAuth or
webhook routes pass their token-bound tenant after verification. Cheap reads are
not throttled.

| Cost class | Routes | Budget per route |
| --- | --- | --- |
| Interactive AI | Ask, search, Slack Ask | 20/minute |
| Provider action | Confirm/approve action, external automation pre-auth, Composio disconnect, SQL source probe | 10/minute |
| Workflow extraction | Start workflow or automation | 10/hour |
| Evaluation batch | Run evals | 3/hour |
| Parse/embed ingestion | Upload, connector sync, Composio sync/ingest | 10/hour |
| Composio OAuth | Connect and signed callback | 10/hour |
| SQL planning | Generate SQL plan | 20/hour |
| SQL execution | Execute approved read-only SQL | 30/minute |

The named budgets live in `api/ratelimit.py`; change them there so route-audit
tests and operations documentation stay aligned.
