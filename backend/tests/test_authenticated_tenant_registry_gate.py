"""Production tenant access must be gated by the platform registry."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tenant_dependency_checks_active_feature_enabled_registry():
    source = (ROOT / "app" / "tenancy" / "dependencies.py").read_text(encoding="utf-8")
    assert "TenantRegistry" in source
    assert 'registry.state != "active"' in source
    assert "feature_enabled" in source
    assert "Tenant registry is unavailable" in source

