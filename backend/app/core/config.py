from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "CRM Chatbot API"

    DATABASE_URL: str

    FACEBOOK_VERIFY_TOKEN: str = "crm_chatbot_2026"
    FACEBOOK_PAGE_ACCESS_TOKEN: str = ""


    FACEBOOK_PAGE_ID: str = ""
    INSTAGRAM_ACCOUNT_ID: str = ""


    INSTAGRAM_ACCESS_TOKEN: str = ""
    PUBLIC_BASE_URL: str = ""
    FRONTEND_BASE_URL: str = "http://localhost:5173"

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
    # gemini | openai

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
    # False keeps embeddings for every seeded document so semantic retrieval
    # is available. Set to true only when intentionally using lexical fallback.
    RAG_AUTO_SEED_FAST_MODE: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
