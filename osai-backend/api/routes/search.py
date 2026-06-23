from typing import Annotated

from fastapi import APIRouter, Depends

from api.schemas.search import SearchRequest, SearchResponse
from db.session import get_org_id
from memory.retriever import retrieve_answer

router = APIRouter(prefix="/search", tags=["search"])
OrgId = Annotated[str, Depends(get_org_id)]


@router.post("", response_model=SearchResponse)
async def search(request: SearchRequest, org_id: OrgId) -> SearchResponse:
    # Enforce the authenticated org from the JWT, not the request body.
    request.org_id = org_id
    return await retrieve_answer(request)
