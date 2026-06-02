# OSAI Backend

FastAPI service for the OSAI MVP. It owns connector registry, sync/search/workflow APIs,
audit events, retrieval orchestration, and the model-router boundary.

## Local Commands

```powershell
uv sync
uv run pytest
uv run alembic upgrade head
uv run python -m db.seed
uv run uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

The local pilot stack is defined in the repository root `docker-compose.yml`.
