import pytest

from app.core.config import Settings


def test_development_can_fall_back_to_legacy_database_url():
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="development",
        DATABASE_URL="postgresql+psycopg://postgres:postgres@db:5432/crm_chatbot",
        PLATFORM_DATABASE_URL="",
        TENANT_DATABASE_URL="",
    )

    with pytest.warns(RuntimeWarning, match="PLATFORM_DATABASE_URL"):
        assert settings.platform_database_url.endswith("/crm_chatbot")
    with pytest.warns(RuntimeWarning, match="TENANT_DATABASE_URL"):
        assert settings.tenant_database_url.endswith("/crm_chatbot")


def test_production_requires_explicit_distinct_database_urls():
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="production",
        DATABASE_URL="postgresql+psycopg://postgres:postgres@db:5432/crm_chatbot",
        PLATFORM_DATABASE_URL="",
        TENANT_DATABASE_URL="",
    )

    with pytest.raises(RuntimeError, match="PLATFORM_DATABASE_URL"):
        settings.validate_runtime()


def test_production_rejects_identical_platform_and_tenant_urls():
    url = "postgresql+psycopg://postgres:postgres@db:5432/crm_platform"
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="production",
        PLATFORM_DATABASE_URL=url,
        TENANT_DATABASE_URL=url,
    )

    with pytest.raises(RuntimeError, match="must be different"):
        settings.validate_runtime()
