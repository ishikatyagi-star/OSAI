from fastapi import APIRouter

from api.schemas.search import SearchRequest, SearchResponse
from memory.retriever import retrieve_answer

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    return await retrieve_answer(request)
