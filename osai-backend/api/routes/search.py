from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.schemas.search import SearchRequest, SearchResponse
from db.repositories import user_clearance, user_permissions
from db.session import get_db, get_optional_claims, get_org_id
from memory.retriever import retrieve_answer

router = APIRouter(prefix="/search", tags=["search"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]


@router.post("", response_model=SearchResponse)
async def search(
    request: SearchRequest, db: DbSession, org_id: OrgId, claims: OptionalClaims
) -> SearchResponse:
    # Org and permissions come from the verified session, never the request body,
    # so a caller cannot read another org's data by passing a different org_id.
    request.org_id = org_id
    request.requester_permissions = user_permissions(db, claims)
    request.requester_tier = user_clearance(db, claims)
    return await retrieve_answer(request)
