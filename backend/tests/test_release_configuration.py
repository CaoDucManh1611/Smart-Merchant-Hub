import pytest

from app.core.config import Settings


def production_settings(**overrides):
    values = {
        "DATABASE_URL": "postgresql+psycopg://crm:password@db.example/crm",
        "ENVIRONMENT": "production",
        "AUTH_SECRET": "auth-secret-for-release-checks-0123456789",
        "CHANNEL_ENCRYPTION_KEY": "channel-key-for-release-checks-0123456789",
        "CORS_ORIGINS": "https://crm.example",
        "ALLOWED_HOSTS": "crm.example",
        "PUBLIC_BASE_URL": "https://crm.example",
        "FRONTEND_BASE_URL": "https://crm.example",
        "FORCE_HTTPS": True,
        "HSTS_ENABLED": True,
        "RATE_LIMIT_ENABLED": True,
        "FACEBOOK_VERIFY_TOKEN": "release-verify-token",
        "LLM_PROVIDER": "groq",
        "GROQ_API_KEYS": "key-a,key-b,key-c,key-d,key-e",
        "EMBEDDING_PROVIDER": "local",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_release_settings_require_a_provider_key_pool():
    settings = production_settings(GROQ_API_KEYS="", GROQ_API_KEY="")

    with pytest.raises(RuntimeError, match="GROQ_API_KEYS"):
        settings.validate_runtime()


def test_production_release_settings_accept_key_pool_and_explicit_security():
    settings = production_settings()

    settings.validate_runtime()
    assert settings.groq_api_keys == ["key-a", "key-b", "key-c", "key-d", "key-e"]


def test_key_pool_configuration_never_exposes_raw_values_in_snapshot():
    from app.services.api_key_pool import ApiKeyPool

    snapshot = ApiKeyPool(["key-a", "key-b"]).snapshot()

    assert snapshot["key_count"] == 2
    assert snapshot["available_count"] == 2
    assert all("key-a" not in str(item) and "key-b" not in str(item) for item in snapshot["keys"])
