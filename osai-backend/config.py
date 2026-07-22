import base64
import ipaddress
import os
from typing import Literal

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
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        # Default email-login availability from the env if not explicitly set.
        if self.email_login_enabled is None:
            self.email_login_enabled = self.env == "local"
        if self.automations_cron_enabled and self.automations_beat_enabled:
            raise ValueError(
                "Only one recurring-automation scheduler may be enabled: set either "
                "OSAI_AUTOMATIONS_CRON_ENABLED or OSAI_AUTOMATIONS_BEAT_ENABLED, not both."
            )
        # A configured-but-unauthenticated sidecar is a public unauthenticated
        # endpoint burning our Groq quota. Require the shared secret alongside
        # the URL in any non-local deployment (mirrors the jwt_secret guard).
        if self.env != "local" and self.hermes_sidecar_url and not self.hermes_sidecar_token:
            raise ValueError(
                "OSAI_HERMES_SIDECAR_TOKEN must be set when OSAI_HERMES_SIDECAR_URL "
                f"is configured and OSAI_ENV is {self.env!r} — the sidecar is a "
                "public endpoint and must not accept unauthenticated /run calls."
            )
        # Zoom is intentionally unavailable: the public route is an unconditional
        # hidden 404. Legacy Zoom env vars must neither enable it nor prevent an
        # otherwise valid deployment from starting.
        # Without a real embedding provider, embeddings silently fall back to
        # deterministic hash vectors (memory/embeddings.py). That is keyword
        # bucketing, not semantic retrieval: Ask keeps answering, just far worse,
        # with nothing in the logs to say why. A misconfigured deployment must
        # fail loudly at boot rather than quietly serve degraded answers (mirrors
        # the guards above). Either Voyage or Gemini satisfies this. Local dev
        # keeps the fallback so the stack runs without a key.
        if self.env != "local" and not (self.gemini_api_key or self.voyage_api_key):
            raise ValueError(
                "An embedding provider key (OSAI_VOYAGE_API_KEY or "
                "OSAI_GEMINI_API_KEY) must be set when OSAI_ENV is "
                f"{self.env!r} — without one, embeddings silently degrade to "
                "non-semantic hash vectors and retrieval quality collapses with "
                "no error. Set a key, or run with OSAI_ENV=local to use the "
                "hash fallback deliberately."
            )
        has_trusted_proxies = bool(self.rate_limit_trusted_proxy_cidrs)
        if self.rate_limit_forwarded_for_mode == "trusted_chain" and not has_trusted_proxies:
            raise ValueError(
                "OSAI_RATE_LIMIT_TRUSTED_PROXY_CIDRS is required when "
                "OSAI_RATE_LIMIT_FORWARDED_FOR_MODE is 'trusted_chain'"
            )
        if self.rate_limit_forwarded_for_mode != "trusted_chain" and has_trusted_proxies:
            raise ValueError(
                "OSAI_RATE_LIMIT_TRUSTED_PROXY_CIDRS is only valid when "
                "OSAI_RATE_LIMIT_FORWARDED_FOR_MODE is 'trusted_chain'"
            )
        if (
            self.rate_limit_forwarded_for_mode == "render_first"
            and os.getenv("RENDER", "").casefold() != "true"
        ):
            raise ValueError(
                "OSAI_RATE_LIMIT_FORWARDED_FOR_MODE='render_first' is only valid "
                "on Render (RENDER=true)"
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
    # Slack signs every slash-command request with this app-level secret. The
    # /slack/ask endpoint fails closed when it is absent; the URL token selects
    # the org but is not a substitute for authenticating Slack itself.
    slack_signing_secret: str | None = None

    # External SQL sources must resolve to globally routable addresses by
    # default. Exact hostnames listed here may resolve to private ranges for
    # deliberately peered/VPN databases; loopback, link-local, metadata, and the
    # app's own control database remain forbidden.
    sql_source_host_allowlist: str = ""

    # Application-level encryption for SQL source credentials. The first key
    # encrypts new values; remaining keys decrypt values during a staged key
    # rotation. Empty is allowed so deployments without SQL sources can boot,
    # but source creation/use fails closed and migration 0032 refuses to carry
    # any legacy plaintext row forward. Each value is a Fernet key.
    sql_dsn_encryption_keys: str = ""

    @field_validator("sql_dsn_encryption_keys")
    @classmethod
    def _valid_sql_dsn_encryption_keys(cls, value: str) -> str:
        keys = [key.strip() for key in value.split(",") if key.strip()]
        if len(keys) != len(set(keys)):
            raise ValueError("SQL DSN encryption keys must be unique")
        for key in keys:
            try:
                decoded = base64.b64decode(key.encode("ascii"), altchars=b"-_", validate=True)
            except (UnicodeEncodeError, ValueError) as exc:
                raise ValueError("each SQL DSN encryption key must be a Fernet key") from exc
            if len(decoded) != 32:
                raise ValueError("each SQL DSN encryption key must decode to 32 bytes")
        return ",".join(keys)

    @property
    def sql_dsn_encryption_key_list(self) -> tuple[str, ...]:
        return tuple(key for key in self.sql_dsn_encryption_keys.split(",") if key)

    @property
    def sql_source_host_allowlist_entries(self) -> list[str]:
        return [
            host.strip().lower().rstrip(".")
            for host in self.sql_source_host_allowlist.split(",")
            if host.strip()
        ]

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

    # Gemini (embeddings always; text generation when no generic LLM key is set)
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    gemini_embedding_model: str = "gemini-embedding-001"

    # Voyage AI embeddings — a no-billing-required alternative to Gemini. When
    # OSAI_VOYAGE_API_KEY is set it takes precedence over Gemini (see
    # memory/embeddings._build_default_provider). voyage-3.5-lite supports an
    # output_dimension of 512/256/1024; keep embedding_dimension in sync and
    # recreate the Qdrant collection when switching providers (the vector space
    # and dimension differ from Gemini's).
    voyage_api_key: str | None = None
    voyage_model: str = "voyage-3.5-lite"
    voyage_base_url: str = "https://api.voyageai.com/v1"

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
    # Exact hosts (or dot-prefixed suffixes) permitted for provider-returned
    # temporary download URLs. Blank fails closed and indexes file metadata only.
    composio_download_hosts: str = ""
    # When true, Ask grounds answers by letting the LLM call the org's connected
    # Composio read tools directly (function-calling), instead of the heuristic
    # live-read. Scales to any connector with no per-app code. Off by default so
    # it can be validated before it becomes the pilot's default grounding path.
    composio_agent_enabled: bool = False

    @property
    def composio_toolkit_list(self) -> list[str]:
        return [t.strip() for t in self.composio_toolkits.split(",") if t.strip()]

    @property
    def composio_download_host_list(self) -> list[str]:
        return [
            host.strip().casefold().rstrip(".")
            for host in self.composio_download_hosts.split(",")
            if host.strip()
        ]

    # Hermes agent sidecar (spike). When set, automations execute via the Hermes
    # agent running as a separate service (HTTP), with OSAI passing org context
    # and enforcing isolation at the boundary. Unset = use the in-house agent.
    hermes_sidecar_url: str | None = None
    # Shared secret sent as X-Sidecar-Token — the sidecar is a separate public
    # service, so both sides must set the same value (SIDECAR_AUTH_TOKEN there).
    hermes_sidecar_token: str | None = None

    # gbrain knowledge-graph CLI integration (P4). When gbrain_home is set, OSAI can
    # read/write the org brain (pages + self-wiring typed graph). Vector/synthesis
    # features need an embedding key; pages + graph + keyword search are key-free.
    gbrain_home: str | None = None  # path to the brain data dir (per org)
    gbrain_cli_dir: str = "../services/gbrain"  # path to the gbrain repo (bun CLI)

    # Redis (for Celery)
    redis_url: str = "redis://localhost:6379/0"

    # Error tracking (Sentry or any Sentry-compatible DSN, e.g. GlitchTip).
    # Unset = telemetry disabled entirely; client errors still land in logs.
    sentry_dsn: str | None = None

    # Shared secret for the GitHub-Actions automations cron (X-Cron-Token on
    # POST /internal/automations/run-due). Unset = the endpoint 404s, so a bare
    # deploy can't be poked into running every org's automations by strangers.
    automations_cron_token: str | None = None
    automations_cron_enabled: bool = True
    automations_beat_enabled: bool = False

    # Rate limiting uses Redis in non-local deployments. Both backends cap active
    # client/route buckets; the Redis cap is enforced atomically by its Lua script.
    rate_limit_memory_max_keys: int = 10_000
    rate_limit_redis_max_keys: int = 10_000
    # IPv6 clients are grouped by prefix so one allocation cannot mint effectively
    # unlimited limiter identities. 128 restores per-address behavior if required.
    rate_limit_ipv6_prefix_length: int = 64
    # Uvicorn is always started with --no-proxy-headers; this setting is the sole
    # owner of forwarded-address trust. Render guarantees the first XFF address is
    # the real client. Other proxies must use an explicit trusted CIDR chain.
    rate_limit_forwarded_for_mode: Literal["direct", "trusted_chain", "render_first"] = "direct"
    rate_limit_trusted_proxy_cidrs: str = ""

    @field_validator("rate_limit_memory_max_keys", "rate_limit_redis_max_keys")
    @classmethod
    def _valid_rate_limit_max_keys(cls, value: int) -> int:
        if not 1 <= value <= 100_000:
            raise ValueError("must be between 1 and 100000")
        return value

    @field_validator("rate_limit_ipv6_prefix_length")
    @classmethod
    def _valid_rate_limit_ipv6_prefix_length(cls, value: int) -> int:
        if not 32 <= value <= 128:
            raise ValueError("must be between 32 and 128")
        return value

    @field_validator("rate_limit_trusted_proxy_cidrs")
    @classmethod
    def _valid_rate_limit_trusted_proxy_cidrs(cls, value: str) -> str:
        networks: list[str] = []
        for raw_network in value.split(","):
            raw_network = raw_network.strip()
            if not raw_network:
                continue
            try:
                network = ipaddress.ip_network(raw_network, strict=False)
            except ValueError as exc:
                raise ValueError(f"invalid trusted-proxy CIDR: {raw_network}") from exc
            if network.prefixlen == 0:
                raise ValueError("trusted-proxy CIDRs must not trust the entire internet")
            networks.append(str(network))
        return ",".join(networks)

    # Reserved for a future tenant-bound, OAuth-authenticated Zoom integration.
    # The current webhook route stays unavailable regardless of this legacy flag.
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
