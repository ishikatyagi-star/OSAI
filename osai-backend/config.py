from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OSAI_", env_file=".env", extra="ignore")

    env: str = "local"
    database_url: str = "postgresql+psycopg://osai:osai@localhost:5433/osai"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "osai_chunks"
    embedding_dimension: int = 768  # Gemini text-embedding-004; set 64 to use hash fallback
    default_org_id: str = "demo-org"
    allowed_origins: str = "http://localhost:3000"

    # Notion
    notion_api_token: str | None = None
    notion_root_page_id: str | None = None

    # Slack
    slack_bot_token: str | None = None

    # Freshdesk
    freshdesk_domain: str | None = None  # e.g. "yourcompany.freshdesk.com"
    freshdesk_api_key: str | None = None

    # Google Drive (service account JSON path or OAuth token)
    google_service_account_json: str | None = None  # path to service account JSON file
    google_drive_folder_id: str | None = None  # optional root folder to scope crawl

    # Gemini (LLM + embeddings) — required for real search/workflows
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    gemini_embedding_model: str = "gemini-embedding-001"

    # Redis (for Celery)
    redis_url: str = "redis://localhost:6379/0"

    # Zoom webhooks
    zoom_webhook_secret: str | None = None

    # OpenAI API Key (for Whisper transcription)
    openai_api_key: str | None = None

    # Ollama (local LLM)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    @property
    def allowed_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


settings = Settings()
