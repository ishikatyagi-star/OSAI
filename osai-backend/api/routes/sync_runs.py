from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db.models import now_utc, utc_iso
from db.repositories import list_sync_runs as list_db_sync_runs
from db.repositories import sync_run_page as get_db_sync_run_page
from db.session import get_db, get_org_id

router = APIRouter(prefix="/sync-runs", tags=["sync-runs"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]


def _row(run: object) -> dict[str, object]:
    return {
        "id": run.id,
        "connector_key": run.connector_key,
        "status": run.status,
        "started_at": utc_iso(run.started_at),
        "documents_seen": run.documents_seen,
        "documents_indexed": run.documents_indexed,
        "error": run.error,
    }


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
    return [_row(run) for run in runs]


@router.get("/page")
async def paginated_sync_runs(
    db: DbSession,
    org_id: OrgId,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> dict[str, object]:
    """Cursor-paginated history with all-time totals and source aggregates."""
    try:
        runs, next_cursor, summary = get_db_sync_run_page(
            db, org_id, limit=limit, cursor=cursor
        )
    except LookupError as exc:
        raise HTTPException(status_code=422, detail="Invalid sync-run cursor.") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Sync history is unavailable: the workspace database could not "
                "be reached. Your syncs are not lost."
            ),
        ) from exc
    return {
        "items": [_row(run) for run in runs],
        "next_cursor": next_cursor,
        "summary": summary,
        "as_of": utc_iso(now_utc()),
    }
