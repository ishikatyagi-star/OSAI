# OSAI Backend

```powershell
uv sync
uv run pytest
uv run alembic upgrade head
uv run python -m db.seed
uv run uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Notion direct API sync uses `OSAI_NOTION_API_TOKEN`. Optionally set
`OSAI_NOTION_ROOT_PAGE_ID` to sync a specific page subtree; otherwise the connector searches
the integration-visible workspace.
