"""Release contracts forbidding legacy tenant bootstrap in production."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import Settings


ROOT = Path(__file__).parents[2]


def test_production_rejects_legacy_tenant_header_compatibility():
    config = Settings(
        ENVIRONMENT="production",
        AUTH_SECRET="release-auth-secret-01234567890123456789",
        CHANNEL_ENCRYPTION_KEY="release-channel-secret-0123456789012345",
        CHANNEL_ROUTE_SECRET="release-route-secret-012345678901234567",
        PLATFORM_DATABASE_URL="postgresql+psycopg://platform:password@db/platform",
        TENANT_DATABASE_URL="postgresql+psycopg://tenant:password@db/tenant",
        CORS_ORIGINS="https://crm.example",
        ALLOWED_HOSTS="crm.example",
        PUBLIC_BASE_URL="https://crm.example",
        FRONTEND_BASE_URL="https://crm.example",
        FORCE_HTTPS=True,
        HSTS_ENABLED=True,
        RATE_LIMIT_ENABLED=True,
        OTP_DELIVERY_MODE="smtp",
        OTP_SMTP_HOST="smtp.example",
        OTP_FROM_EMAIL="no-reply@example.com",
        OTP_SMTP_USERNAME="smtp-user",
        OTP_SMTP_PASSWORD="smtp-password",
        FACEBOOK_VERIFY_TOKEN="verify-token",
        LLM_PROVIDER="local",
        EMBEDDING_PROVIDER="local",
        ALLOW_LEGACY_TENANT_HEADER=True,
    )

    with pytest.raises(RuntimeError, match="ALLOW_LEGACY_TENANT_HEADER"):
        config.validate_runtime()


def test_production_startup_checks_migrations_without_mutating_schema(monkeypatch):
    from app import main

    monkeypatch.setattr(main.settings, "ENVIRONMENT", "production")
    with patch("app.core.config.Settings.validate_runtime") as validate, patch(
        "app.main.assert_release_database_ready", create=True
    ) as ready, patch("app.main.init_db") as legacy_init:
        main.initialize_database()

    validate.assert_called_once_with()
    ready.assert_called_once_with()
    legacy_init.assert_not_called()


def test_legacy_channel_migration_does_not_fallback_to_global_tokens():
    source = (ROOT / "backend" / "app" / "services" / "legacy_channel_migration.py").read_text(
        encoding="utf-8"
    )

    assert "settings.FACEBOOK_PAGE_ACCESS_TOKEN" not in source
    assert "settings.INSTAGRAM_ACCESS_TOKEN" not in source


def test_release_smoke_has_no_optional_verification_warnings():
    source = (ROOT / "scripts" / "release-smoke.ps1").read_text(encoding="utf-8")

    assert "Write-Warning" not in source
    assert "alembic-platform.ini" in source
    assert "alembic-tenant.ini" in source
    assert "pytest" in source
    assert "npm" in source and "test" in source
