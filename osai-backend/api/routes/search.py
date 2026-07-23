from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.ratelimit import INTERACTIVE_AI_BUDGET, rate_limit
from api.schemas.search import SearchRequest, SearchResponse
from db.repositories import user_clearance, user_permissions
from db.session import get_db, get_optional_claims, require_writable_org
from memory.retriever import retrieve_answer

router = APIRouter(prefix="/search", tags=["search"])
DbSession = Annotated[Session, Depends(get_db)]
WriteOrgId = Annotated[str, Depends(require_writable_org)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]


@router.post(
    "",
    response_model=SearchResponse,
    dependencies=[Depends(rate_limit(*INTERACTIVE_AI_BUDGET))],
)
async def search(
    request: SearchRequest, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims
) -> SearchResponse:
    # Org and permissions come from the verified session, never the request body,
    # so a caller cannot read another org's data by passing a different org_id.
    request.org_id = org_id
    request.requester_permissions = user_permissions(db, claims)
    request.requester_tier = user_clearance(db, claims)
    request.requester_user_id = claims.get("sub") if claims else None
    return await retrieve_answer(request)
