from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OSAI_", env_file=".env", extra="ignore")

    env: str = "local"
    database_url: str = "postgresql+psycopg://osai:osai@localhost:5433/osai"

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, v: str) -> str:
        # Managed providers (Render, Railway, Heroku) hand out postgres:// or
        # postgresql:// URLs; SQLAlchemy here needs the psycopg driver prefix.
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://") :]
        return v
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None  # required for Qdrant Cloud (free tier)
    qdrant_collection: str = "osai_chunks"
    embedding_dimension: int = 768  # Gemini text-embedding-004; set 64 to use hash fallback
    default_org_id: str = "demo-org"

    # Session JWT signing. MUST be set to a strong random value in production
    # (Render env). If unset, a fixed dev secret is used so local dev works, but
    # tokens would be forgeable — never rely on the default in prod.
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_expiry_hours: int = 720  # 30 days — long-lived for the pilot
    allowed_origins: str = "http://localhost:3000"
    # Public URLs (for the OAuth auto-ingest callback). On Render set these to the
    # live API URL and the Vercel frontend URL.
    public_base_url: str | None = None
    frontend_url: str | None = None

    @property
    def frontend_redirect(self) -> str:
        if self.frontend_url:
            return self.frontend_url
        return self.allowed_origin_list[0] if self.allowed_origin_list else "/"

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

    # Google sign-in (OAuth 2.0 / OIDC). Distinct from the Drive service account
    # above — these power "Continue with Google" user authentication. Register the
    # redirect URI in the Google Cloud OAuth consent screen (dev + prod).
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_redirect_uri: str | None = None  # e.g. http://localhost:8000/auth/google/callback

    @property
    def google_oauth_enabled(self) -> bool:
        return bool(
            self.google_oauth_client_id
            and self.google_oauth_client_secret
            and self.google_oauth_redirect_uri
        )

    # Gemini (embeddings always; text-gen if no OpenRouter key set)
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    gemini_embedding_model: str = "gemini-embedding-001"

    # LLM text generation — any OpenAI-compatible provider (Groq, OpenRouter,
    # GitHub Models, Cerebras, Mistral, …). When set, it is the preferred provider
    # for answer synthesis / planning / extraction. Embeddings still use Gemini.
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "llama-3.3-70b-versatile"

    # Composio — universal tool/integration layer (P2). When set, its tools are
    # exposed to the agent alongside native connectors. no_auth tools (e.g. web
    # search) work immediately; OAuth tools (Gmail, Calendar) need a connection.
    composio_api_key: str | None = None
    composio_base_url: str = "https://backend.composio.dev"
    composio_toolkits: str = "composio_search"  # comma-separated toolkit slugs to expose

    @property
    def composio_toolkit_list(self) -> list[str]:
        return [t.strip() for t in self.composio_toolkits.split(",") if t.strip()]

    # Hermes agent sidecar (spike). When set, automations execute via the Hermes
    # agent running as a separate service (HTTP), with OSAI passing org context
    # and enforcing isolation at the boundary. Unset = use the in-house agent.
    hermes_sidecar_url: str | None = None

    # gbrain knowledge-graph sidecar (P4). When gbrain_home is set, OSAI can
    # read/write the org brain (pages + self-wiring typed graph). Vector/synthesis
    # features need an embedding key; pages + graph + keyword search are key-free.
    gbrain_home: str | None = None  # path to the brain data dir (per org)
    gbrain_cli_dir: str = "../services/gbrain"  # path to the gbrain repo (bun CLI)

    # Redis (for Celery)
    redis_url: str = "redis://localhost:6379/0"

    # Zoom webhooks
    zoom_webhook_secret: str | None = None

    # OpenAI API Key (legacy; Whisper now defaults to Groq below)
    openai_api_key: str | None = None

    # Media transcription (Whisper). Defaults to Groq's free whisper-large-v3 and
    # reuses the existing LLM (Groq) key — no separate paid OpenAI account needed.
    transcribe_base_url: str = "https://api.groq.com/openai/v1"
    transcribe_model: str = "whisper-large-v3"
    transcribe_api_key: str | None = None  # falls back to llm_api_key (Groq)

    @property
    def transcribe_key(self) -> str | None:
        return self.transcribe_api_key or self.llm_api_key

    # Ollama (local LLM)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    @property
    def allowed_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


settings = Settings()
