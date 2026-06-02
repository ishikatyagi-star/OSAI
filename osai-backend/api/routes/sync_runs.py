from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config import settings
from db.repositories import list_sync_runs as list_db_sync_runs
from db.repositories import try_db
from db.session import get_db

router = APIRouter(prefix="/sync-runs", tags=["sync-runs"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("")
async def list_sync_runs(db: DbSession) -> list[dict[str, object]]:
    fallback = [
        {
            "id": "seed-sync-notion",
            "connector_key": "notion",
            "status": "succeeded",
            "started_at": datetime.now(UTC).isoformat(),
            "documents_seen": 0,
            "documents_indexed": 0,
            "error": None,
        }
    ]
    return try_db(
        "list_sync_runs",
        fallback,
        lambda: [
            {
                "id": run.id,
                "connector_key": run.connector_key,
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "documents_seen": run.documents_seen,
                "documents_indexed": run.documents_indexed,
                "error": run.error,
            }
            for run in list_db_sync_runs(db, settings.default_org_id)
        ]
        or fallback,
    )
