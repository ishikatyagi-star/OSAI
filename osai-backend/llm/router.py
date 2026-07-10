from dataclasses import dataclass

from api.schemas.connector import DataTier
from config import settings


@dataclass(frozen=True)
class ModelRoute:
    name: str
    provider: str
    model: str
    data_tier: DataTier


class ModelRouter:
    def route(self, use_case: str, data_tier: DataTier) -> ModelRoute:
        if data_tier == "red":
            return ModelRoute(
                name=f"{use_case}:local-only",
                provider="local",
                model=settings.ollama_model,
                data_tier=data_tier,
            )
        return ModelRoute(
            name=f"{use_case}:cloud-default",
            provider="cloud",
            model=settings.llm_model if settings.llm_api_key else settings.gemini_model,
            data_tier=data_tier,
        )


model_router = ModelRouter()
