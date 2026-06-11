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

    # Gemini (embeddings always; text-gen if no OpenRouter key set)
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    gemini_embedding_model: str = "gemini-embedding-001"

    # OpenRouter (OpenAI-compatible text generation gateway). When set, it is the
    # preferred provider for answer synthesis / planning / extraction. Embeddings
    # still use Gemini.
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemini-2.0-flash-001"

    # gbrain knowledge-graph sidecar (P4). When gbrain_home is set, OSAI can
    # read/write the org brain (pages + self-wiring typed graph). Vector/synthesis
    # features need an embedding key; pages + graph + keyword search are key-free.
    gbrain_home: str | None = None  # path to the brain data dir (per org)
    gbrain_cli_dir: str = "../services/gbrain"  # path to the gbrain repo (bun CLI)

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
