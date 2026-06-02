from config import settings


class QdrantStore:
    def __init__(self, url: str = settings.qdrant_url) -> None:
        self.url = url

    async def healthcheck(self) -> dict[str, str]:
        return {"status": "not_connected", "url": self.url}
