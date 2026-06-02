from api.schemas.search import SearchRequest, SearchResponse


async def retrieve_answer(request: SearchRequest) -> SearchResponse:
    return SearchResponse(
        answer="I do not have enough connected context yet.",
        citations=[],
        enough_context=False,
    )
