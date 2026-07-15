from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db.repositories import list_sync_runs as list_db_sync_runs
from db.session import get_db, get_org_id

router = APIRouter(prefix="/sync-runs", tags=["sync-runs"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]


@router.get("")
async def list_sync_runs(db: DbSession, org_id: OrgId) -> list[dict[str, object]]:
    """The org's real sync history.

    Neither a database failure nor an empty history may be answered with an
    invented run. This used to return a fabricated "seed-sync-notion /
    not_started" entry in *both* cases, so a workspace that had never synced
    anything was shown a Notion sync that never happened, and a database outage
    looked identical to it. A workspace with no syncs returns []; an unreachable
    database says so (SHE-6 P1 "do not convert database/service failures").
    """
    try:
        runs = list_db_sync_runs(db, org_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Sync history is unavailable: the workspace database could not "
                "be reached. Your syncs are not lost."
            ),
        ) from exc
    return [
        {
            "id": run.id,
            "connector_key": run.connector_key,
            "status": run.status,
            "started_at": run.started_at.isoformat(),
            "documents_seen": run.documents_seen,
            "documents_indexed": run.documents_indexed,
            "error": run.error,
        }
        for run in runs
    ]
