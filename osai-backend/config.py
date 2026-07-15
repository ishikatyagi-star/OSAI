from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"


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

    @model_validator(mode="after")
    def _require_strong_jwt_secret_in_prod(self) -> "Settings":
        # In any non-local deployment, refuse to boot with the committed dev
        # secret or a weak one — otherwise sessions (incl. role:admin) would be
        # forgeable by anyone who knows the public default.
        if self.env != "local" and (
            self.jwt_secret == _DEV_JWT_SECRET or len(self.jwt_secret) < 32
        ):
            raise ValueError(
                "OSAI_JWT_SECRET must be set to a strong random value (>=32 chars) "
                f"when OSAI_ENV is {self.env!r}. Generate one with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        # Default email-login availability from the env if not explicitly set.
        if self.email_login_enabled is None:
            self.email_login_enabled = self.env == "local"
        # A configured-but-unauthenticated sidecar is a public unauthenticated
        # endpoint burning our Groq quota. Require the shared secret alongside
        # the URL in any non-local deployment (mirrors the jwt_secret guard).
        if (
            self.env != "local"
            and self.hermes_sidecar_url
            and not self.hermes_sidecar_token
        ):
            raise ValueError(
                "OSAI_HERMES_SIDECAR_TOKEN must be set when OSAI_HERMES_SIDECAR_URL "
                f"is configured and OSAI_ENV is {self.env!r} — the sidecar is a "
                "public endpoint and must not accept unauthenticated /run calls."
            )
        # The Zoom webhook is public; an enabled-but-secretless webhook accepts
        # forged recording events. Require the secret whenever it's enabled in a
        # non-local deployment (mirrors the sidecar guard above).
        if (
            self.env != "local"
            and self.zoom_webhook_enabled
            and not self.zoom_webhook_secret
        ):
            raise ValueError(
                "OSAI_ZOOM_WEBHOOK_SECRET must be set when OSAI_ZOOM_WEBHOOK_ENABLED "
                f"is true and OSAI_ENV is {self.env!r} — the webhook is public and "
                "must verify Zoom's signature, not accept unauthenticated events."
            )
        # Without a Gemini key, embeddings silently fall back to deterministic
        # hash vectors (memory/embeddings.py). That is keyword bucketing, not
        # semantic retrieval: Ask keeps answering, just far worse, with nothing
        # in the logs to say why. A misconfigured deployment must fail loudly at
        # boot rather than quietly serve degraded answers (mirrors the guards
        # above). Local dev keeps the fallback so the stack runs without a key.
        if self.env != "local" and not self.gemini_api_key:
            raise ValueError(
                "OSAI_GEMINI_API_KEY must be set when OSAI_ENV is "
                f"{self.env!r} — without it embeddings silently degrade to "
                "non-semantic hash vectors and retrieval quality collapses with "
                "no error. Set the key, or run with OSAI_ENV=local to use the "
                "hash fallback deliberately."
            )
        return self

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None  # required for Qdrant Cloud (free tier)
    qdrant_collection: str = "osai_chunks"
    embedding_dimension: int = 768  # Gemini text-embedding-004; set 64 to use hash fallback
    default_org_id: str = "demo-org"

    # Session JWT signing. MUST be set to a strong random value in production
    # (Render env). If unset, a fixed dev secret is used so local dev works, but
    # tokens would be forgeable — never rely on the default in prod.
    jwt_secret: str = _DEV_JWT_SECRET
    jwt_expiry_hours: int = 720  # 30 days — long-lived for the pilot
    # Password-less email-lookup login (/auth/login) is a dev/demo convenience and
    # a real auth bypass in production (anyone who knows an email gets that
    # session). Off outside local by default; Google OAuth is the real sign-in.
    # Override with OSAI_EMAIL_LOGIN_ENABLED=true if a deploy still needs it.
    email_login_enabled: bool | None = None
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
    # Supermemory (supermemory.ai) memory backbone. Key absent = disabled
    # (Postgres org-memory only). URL overrides the cloud endpoint for the
    # self-hosted binary — required before amber/red content may be stored.
    supermemory_api_key: str | None = None
    supermemory_url: str | None = None

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

    # Minimum cosine similarity for a retrieved chunk to count as relevant. Below
    # this floor, an off-topic query returns "no relevant context" instead of
    # surfacing the nearest (but unrelated) documents at misleading confidence.
    retrieval_min_score: float = 0.7

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
    # Shared secret sent as X-Sidecar-Token — the sidecar is a separate public
    # service, so both sides must set the same value (SIDECAR_AUTH_TOKEN there).
    hermes_sidecar_token: str | None = None

    # gbrain knowledge-graph sidecar (P4). When gbrain_home is set, OSAI can
    # read/write the org brain (pages + self-wiring typed graph). Vector/synthesis
    # features need an embedding key; pages + graph + keyword search are key-free.
    gbrain_home: str | None = None  # path to the brain data dir (per org)
    gbrain_cli_dir: str = "../services/gbrain"  # path to the gbrain repo (bun CLI)

    # Redis (for Celery)
    redis_url: str = "redis://localhost:6379/0"

    # Zoom webhooks. Disabled by default: the ingestion path is still hardcoded to
    # the demo org and its transcription task needs a Celery worker (not deployed
    # on the free tier), so the endpoint stays off — and 404s — until explicitly
    # enabled with a configured secret.
    zoom_webhook_enabled: bool = False
    zoom_webhook_secret: str | None = None

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
