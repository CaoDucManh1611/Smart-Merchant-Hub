"""Provider configuration must be resolved from the active tenant schema."""

from pathlib import Path

from app.models.business_setting import BusinessSetting
from app.models.channel import Channel
from app.database.bases import TenantBase


ROOT = Path(__file__).resolve().parents[1]


def test_provider_credentials_are_tenant_models():
    assert BusinessSetting in {mapper.class_ for mapper in TenantBase.registry.mappers}
    assert Channel in {mapper.class_ for mapper in TenantBase.registry.mappers}


def test_meta_config_does_not_use_global_app_setting_or_legacy_tokens():
    source = (ROOT / "app" / "services" / "meta_config_service.py").read_text(encoding="utf-8")
    assert "AppSetting" not in source
    assert "SessionLocal" not in source
    assert "FACEBOOK_PAGE_ACCESS_TOKEN" not in source
    assert "get_tenant_db" in source


def test_instagram_outbound_has_no_process_wide_token_fallback():
    source = (ROOT / "app" / "services" / "instagram_service.py").read_text(encoding="utf-8")
    assert "settings.INSTAGRAM_ACCESS_TOKEN" not in source
    assert "Tenant context is required" in source
    assert "get_single_active_channel" in source


def test_facebook_outbound_has_no_process_wide_token_fallback():
    source = (ROOT / "app" / "services" / "facebook_service.py").read_text(encoding="utf-8")
    assert "settings.FACEBOOK_PAGE_ACCESS_TOKEN" not in source
    assert "Tenant context is required" in source
    assert "get_single_active_channel" in source
