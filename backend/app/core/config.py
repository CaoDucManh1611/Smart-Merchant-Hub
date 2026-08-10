from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "CRM Chatbot API"

    DATABASE_URL: str

    FACEBOOK_VERIFY_TOKEN: str = "crm_chatbot_2026"
    FACEBOOK_PAGE_ACCESS_TOKEN: str = ""

    INSTAGRAM_ACCESS_TOKEN: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()