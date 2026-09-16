import warnings

from pydantic import PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.secret_manager import load_runtime_secrets


class Settings(BaseSettings):
    _database_fallback_warned: set[str] = PrivateAttr(default_factory=set)

    APP_NAME: str = "CRM Chatbot API"
    ENVIRONMENT: str = "development"
    CHANNEL_ENCRYPTION_KEY: str = ""
    CHANNEL_ROUTE_SECRET: str = ""
    AUTH_SECRET: str = ""
    SECRET_MANAGER_MODE: str = "env"
    SECRET_MANAGER_FILE: str = ""

    DATABASE_URL: str = ""
    PLATFORM_DATABASE_URL: str = ""
    TENANT_DATABASE_URL: str = ""
    # Compatibility is opt-in for local fixtures only. Production tenant
    # identity always comes from the authenticated session or webhook route.
    ALLOW_LEGACY_TENANT_HEADER: bool = False

    # Never rely on this development value in a deployed environment.  A
    # real value must be supplied through the secret manager/.env file.
    FACEBOOK_VERIFY_TOKEN: str = ""
    FACEBOOK_PAGE_ACCESS_TOKEN: str = ""


    FACEBOOK_PAGE_ID: str = ""
    INSTAGRAM_ACCOUNT_ID: str = ""


    INSTAGRAM_ACCESS_TOKEN: str = ""
    PUBLIC_BASE_URL: str = ""
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    # Runtime security controls.  Comma-separated values keep the settings
    # compatible with Docker Compose and Pydantic Settings on Windows/Linux.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    ALLOWED_HOSTS: str = "*"
    FORCE_HTTPS: bool = False
    HSTS_ENABLED: bool = False
    RATE_LIMIT_ENABLED: bool = False
    RATE_LIMIT_REQUESTS: int = 120
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_BACKEND: str = "memory"
    RATE_LIMIT_TRUSTED_PROXY: bool = False
    REDIS_URL: str = ""
    ALERT_QUEUE_PENDING_THRESHOLD: int = 100
    ALERT_AI_COST_THRESHOLD: float = 50.0
    DATA_RETENTION_DAYS: int = 365
    QUOTA_WARNING_PERCENT: float = 0.8
    TICKET_SLA_WARNING_MINUTES: int = 60
    CHANNEL_HEALTH_INTERVAL_SECONDS: int = 60

    # Contact verification delivery.  Keep disabled for local/demo runs; a
    # production secret manager should select smtp (email) or twilio (SMS).
    OTP_DELIVERY_MODE: str = "disabled"
    OTP_DELIVERY_FALLBACK: str = "disabled"
    OTP_FROM_EMAIL: str = ""
    OTP_SMTP_HOST: str = ""
    OTP_SMTP_PORT: int = 587
    OTP_SMTP_USERNAME: str = ""
    OTP_SMTP_PASSWORD: str = ""
    OTP_SMTP_USE_TLS: bool = True
    OTP_TWILIO_ACCOUNT_SID: str = ""
    OTP_TWILIO_AUTH_TOKEN: str = ""
    OTP_TWILIO_FROM_NUMBER: str = ""

    # Meta OAuth integration
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_GRAPH_VERSION: str = "v26.0"
    META_OAUTH_REDIRECT_URI: str = ""
    META_DEFAULT_PAGE_ID: str = ""

    # TikTok Shop webhook authentication
    TIKTOK_APP_KEY: str = ""
    TIKTOK_APP_SECRET: str = ""

    # =========================================================
    # RAG SETTINGS
    # =========================================================

    LLM_PROVIDER: str = "groq"
    # groq | gemini | openai

    LLM_API_KEY: str = ""
    LLM_API_KEYS: str = ""
    GROQ_API_KEY: str = ""
    GROQ_API_KEYS: str = ""

    LLM_MODEL: str = "openai/gpt-oss-20b"
    # openai/gpt-oss-20b | gemini-3.6-flash | gpt-4o-mini

    EMBEDDING_PROVIDER: str = "gemini"
    # local | gemini | openai

    EMBEDDING_API_KEY: str = ""
    EMBEDDING_API_KEYS: str = ""
    API_KEY_COOLDOWN_SECONDS: int = 60
    EMBEDDING_MODEL: str = "gemini-embedding-001"
    # gemini-embedding-001 | text-embedding-3-small

    EMBEDDING_DIMENSION: int = 3072

    RAG_CHUNK_SIZE: int = 800
    RAG_CHUNK_OVERLAP: int = 100
    RAG_TOP_K: int = 5
    RAG_SIMILARITY_THRESHOLD: float = 0.3
    RAG_LOG_FILE: str = "rag_runs.jsonl"
    RAG_AUTO_SEED_ENABLED: bool = True
    RAG_AUTO_SEED_DIR: str = "sample_data/knowledge_base"
    # Auto-reply defaults to on for the demo/development deployment. A row in
    # app_settings or this environment variable can still turn it off.
    RAG_AUTO_REPLY_ENABLED: bool = True
    # Extract durable customer facts in a background worker. Keep this
    # opt-in so a deployment never starts making LLM calls unexpectedly.
    CUSTOMER_FACT_EXTRACTION_ENABLED: bool = False
    # False keeps embeddings for every seeded document so semantic retrieval
    # is available. Set to true only when intentionally using lexical fallback.
    RAG_AUTO_SEED_FAST_MODE: bool = False

    # The provider response does not expose a uniform token-usage contract
    # across Groq, Gemini and OpenAI. Keep a conservative, configurable
    # estimate so tenant AI-cost quotas are enforced consistently; production
    # deployments can replace the rate with their billing price.
    AI_COST_PER_1K_TOKENS: float = 0.002
    AI_MAX_OUTPUT_TOKENS_ESTIMATE: int = 512

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @staticmethod
    def _csv(value: str) -> list[str]:
        return [item.strip() for item in str(value or "").split(",") if item.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return self._csv(self.CORS_ORIGINS)

    @property
    def allowed_hosts(self) -> list[str]:
        return self._csv(self.ALLOWED_HOSTS) or ["*"]

    @property
    def llm_api_keys(self) -> list[str]:
        return self._csv(self.LLM_API_KEYS) or self._csv(self.LLM_API_KEY)

    @property
    def groq_api_keys(self) -> list[str]:
        return self._csv(self.GROQ_API_KEYS) or self._csv(self.GROQ_API_KEY)

    @property
    def embedding_api_keys(self) -> list[str]:
        return self._csv(self.EMBEDDING_API_KEYS) or self._csv(self.EMBEDDING_API_KEY) or self.llm_api_keys

    def _database_url(self, explicit_value: str, setting_name: str) -> str:
        value = str(explicit_value or "").strip()
        if value:
            return value
        legacy = str(self.DATABASE_URL or "").strip()
        if legacy and self.ENVIRONMENT.strip().lower() != "production":
            if setting_name not in self._database_fallback_warned:
                warnings.warn(
                    f"{setting_name} is falling back to legacy DATABASE_URL; configure the explicit URL before production",
                    RuntimeWarning,
                    stacklevel=2,
                )
                self._database_fallback_warned.add(setting_name)
            return legacy
        return ""

    @property
    def platform_database_url(self) -> str:
        return self._database_url(self.PLATFORM_DATABASE_URL, "PLATFORM_DATABASE_URL")

    @property
    def tenant_database_url(self) -> str:
        return self._database_url(self.TENANT_DATABASE_URL, "TENANT_DATABASE_URL")

    def validate_runtime(self) -> None:
        """Fail closed for settings that are unsafe in production.

        Development keeps the existing local workflow.  Production must
        explicitly provide secrets, HTTPS URLs, non-wildcard CORS/hosts and
        a real PostgreSQL URL; no insecure fallback is accepted.
        """
        if self.ENVIRONMENT.strip().lower() != "production":
            return

        problems: list[str] = []
        placeholders = {"", "change-me", "changeme", "secret", "postgres"}
        if self.AUTH_SECRET.strip().lower() in placeholders or len(self.AUTH_SECRET.strip()) < 32:
            problems.append("AUTH_SECRET must be a random value of at least 32 characters")
        if self.CHANNEL_ENCRYPTION_KEY.strip().lower() in placeholders or len(self.CHANNEL_ENCRYPTION_KEY.strip()) < 32:
            problems.append("CHANNEL_ENCRYPTION_KEY must be a random value of at least 32 characters")
        if self.CHANNEL_ROUTE_SECRET.strip().lower() in placeholders or len(self.CHANNEL_ROUTE_SECRET.strip()) < 32:
            problems.append("CHANNEL_ROUTE_SECRET must be a random value of at least 32 characters")
        platform_url = self.PLATFORM_DATABASE_URL.strip()
        tenant_url = self.TENANT_DATABASE_URL.strip()
        if not platform_url:
            problems.append("PLATFORM_DATABASE_URL must be configured in production")
        elif not platform_url.lower().startswith(("postgresql://", "postgresql+psycopg://")):
            problems.append("PLATFORM_DATABASE_URL must point to PostgreSQL")
        if not tenant_url:
            problems.append("TENANT_DATABASE_URL must be configured in production")
        elif not tenant_url.lower().startswith(("postgresql://", "postgresql+psycopg://")):
            problems.append("TENANT_DATABASE_URL must point to PostgreSQL")
        if platform_url and tenant_url and platform_url == tenant_url:
            problems.append("PLATFORM_DATABASE_URL and TENANT_DATABASE_URL must be different in production")
        if self.ALLOW_LEGACY_TENANT_HEADER:
            problems.append("ALLOW_LEGACY_TENANT_HEADER must be false in production")
        if not self.cors_origins or "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must be an explicit allowlist")
        if not self.allowed_hosts or "*" in self.allowed_hosts:
            problems.append("ALLOWED_HOSTS must be an explicit allowlist")
        if not self.PUBLIC_BASE_URL.lower().startswith("https://"):
            problems.append("PUBLIC_BASE_URL must use HTTPS")
        if not self.FRONTEND_BASE_URL.lower().startswith("https://"):
            problems.append("FRONTEND_BASE_URL must use HTTPS")
        if not self.FORCE_HTTPS:
            problems.append("FORCE_HTTPS must be true")
        if not self.HSTS_ENABLED:
            problems.append("HSTS_ENABLED must be true")
        if not self.FACEBOOK_VERIFY_TOKEN.strip():
            problems.append("FACEBOOK_VERIFY_TOKEN must be configured")
        if self.LLM_PROVIDER.strip().lower() == "groq" and not self.groq_api_keys:
            problems.append("GROQ_API_KEYS or GROQ_API_KEY must be configured")
        if self.LLM_PROVIDER.strip().lower() in {"gemini", "openai"} and not self.llm_api_keys:
            problems.append("LLM_API_KEYS or LLM_API_KEY must be configured")
        if self.EMBEDDING_PROVIDER.strip().lower() != "local" and not self.embedding_api_keys:
            problems.append("EMBEDDING_API_KEYS, EMBEDDING_API_KEY, or LLM_API_KEY must be configured")
        if not self.RATE_LIMIT_ENABLED:
            problems.append("RATE_LIMIT_ENABLED must be true")
        if self.RATE_LIMIT_REQUESTS <= 0 or self.RATE_LIMIT_WINDOW_SECONDS <= 0:
            problems.append("RATE_LIMIT_REQUESTS and RATE_LIMIT_WINDOW_SECONDS must be positive")
        rate_limit_backend = self.RATE_LIMIT_BACKEND.strip().lower()
        if rate_limit_backend not in {"memory", "redis", "proxy"}:
            problems.append("RATE_LIMIT_BACKEND must be memory, redis or proxy")
        if rate_limit_backend == "redis" and not self.REDIS_URL.strip():
            problems.append("REDIS_URL must be configured when RATE_LIMIT_BACKEND=redis")
        if rate_limit_backend == "proxy" and not self.RATE_LIMIT_TRUSTED_PROXY:
            problems.append("RATE_LIMIT_TRUSTED_PROXY must be true when RATE_LIMIT_BACKEND=proxy")
        secret_mode = self.SECRET_MANAGER_MODE.strip().lower()
        if secret_mode not in {"env", "environment", "injected", "file", "json", "mounted_file", "disabled", "none"}:
            problems.append("SECRET_MANAGER_MODE must be env or file")
        if secret_mode in {"file", "json", "mounted_file"} and not self.SECRET_MANAGER_FILE.strip():
            problems.append("SECRET_MANAGER_FILE must be configured when file secret-manager mode is enabled")
        if self.DATA_RETENTION_DAYS <= 0:
            problems.append("DATA_RETENTION_DAYS must be positive")
        if self.CHANNEL_HEALTH_INTERVAL_SECONDS <= 0:
            problems.append("CHANNEL_HEALTH_INTERVAL_SECONDS must be positive")
        otp_mode = self.OTP_DELIVERY_MODE.strip().lower()
        if otp_mode not in {"smtp", "twilio"}:
            problems.append("OTP_DELIVERY_MODE must be smtp or twilio in production")
        elif otp_mode == "smtp":
            if not self.OTP_SMTP_HOST.strip() or not self.OTP_FROM_EMAIL.strip():
                problems.append("OTP_SMTP_HOST and OTP_FROM_EMAIL must be configured for SMTP OTP")
            if not self.OTP_SMTP_USERNAME.strip() or not self.OTP_SMTP_PASSWORD:
                problems.append("OTP_SMTP_USERNAME and OTP_SMTP_PASSWORD must be configured for SMTP OTP")
        elif otp_mode == "twilio":
            if not self.OTP_TWILIO_ACCOUNT_SID.strip() or not self.OTP_TWILIO_AUTH_TOKEN.strip() or not self.OTP_TWILIO_FROM_NUMBER.strip():
                problems.append("Twilio OTP credentials and sender number must be configured")
        if self.OTP_DELIVERY_FALLBACK.strip().lower() == "in_chat":
            problems.append("OTP_DELIVERY_FALLBACK=in_chat is not allowed in production")
        if problems:
            raise RuntimeError("Production security configuration is incomplete: " + "; ".join(problems))


settings = Settings()
_secret_overrides = load_runtime_secrets(
    allowed_keys=set(Settings.model_fields),
    mode=settings.SECRET_MANAGER_MODE,
    path=settings.SECRET_MANAGER_FILE,
)
if _secret_overrides:
    settings = Settings(**_secret_overrides)
