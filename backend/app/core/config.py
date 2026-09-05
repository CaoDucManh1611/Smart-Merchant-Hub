from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "CRM Chatbot API"
    ENVIRONMENT: str = "development"
    CHANNEL_ENCRYPTION_KEY: str = ""
    AUTH_SECRET: str = ""

    DATABASE_URL: str

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

    # Meta OAuth integration
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_GRAPH_VERSION: str = "v26.0"
    META_OAUTH_REDIRECT_URI: str = ""
    META_DEFAULT_PAGE_ID: str = ""

    # =========================================================
    # RAG SETTINGS
    # =========================================================

    LLM_PROVIDER: str = "groq"
    # groq | gemini | openai

    LLM_API_KEY: str = ""
    GROQ_API_KEY: str = ""

    LLM_MODEL: str = "openai/gpt-oss-20b"
    # openai/gpt-oss-20b | gemini-3.6-flash | gpt-4o-mini

    EMBEDDING_PROVIDER: str = "gemini"
    # local | gemini | openai

    EMBEDDING_API_KEY: str = ""
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
        if not self.DATABASE_URL.lower().startswith(("postgresql://", "postgresql+psycopg://")):
            problems.append("DATABASE_URL must point to PostgreSQL")
        if not self.cors_origins or "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must be an explicit allowlist")
        if not self.allowed_hosts or "*" in self.allowed_hosts:
            problems.append("ALLOWED_HOSTS must be an explicit allowlist")
        if not self.PUBLIC_BASE_URL.lower().startswith("https://"):
            problems.append("PUBLIC_BASE_URL must use HTTPS")
        if not self.FRONTEND_BASE_URL.lower().startswith("https://"):
            problems.append("FRONTEND_BASE_URL must use HTTPS")
        if not self.FACEBOOK_VERIFY_TOKEN.strip():
            problems.append("FACEBOOK_VERIFY_TOKEN must be configured")
        if not self.RATE_LIMIT_ENABLED:
            problems.append("RATE_LIMIT_ENABLED must be true")
        if self.RATE_LIMIT_REQUESTS <= 0 or self.RATE_LIMIT_WINDOW_SECONDS <= 0:
            problems.append("RATE_LIMIT_REQUESTS and RATE_LIMIT_WINDOW_SECONDS must be positive")
        if problems:
            raise RuntimeError("Production security configuration is incomplete: " + "; ".join(problems))


settings = Settings()
