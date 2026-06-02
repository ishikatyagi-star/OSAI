from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config import settings
from connectors.registry import connector_registry
from db.repositories import list_integrations as list_db_integrations
from db.repositories import try_db
from db.session import get_db

router = APIRouter(prefix="/integrations", tags=["integrations"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("")
async def list_integrations(db: DbSession) -> list[dict[str, object]]:
    fallback = [connector.summary() for connector in connector_registry.all()]
    return try_db(
        "list_integrations",
        fallback,
        lambda: list_db_integrations(db, settings.default_org_id) or fallback,
    )
