from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OSAI_", env_file=".env", extra="ignore")

    env: str = "local"
    database_url: str = "postgresql+psycopg://osai:osai@localhost:5432/osai"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    default_org_id: str = "demo-org"
    allowed_origins: str = "http://localhost:3000"
    red_tier_cloud_allowed: bool = False

    @property
    def allowed_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


settings = Settings()
