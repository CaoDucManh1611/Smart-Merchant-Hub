"""Provision endpoints expose status only and preserve retry semantics."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_onboarding_exposes_idempotent_provision_and_retry_routes():
    source = (ROOT / "app" / "api" / "onboarding.py").read_text(encoding="utf-8")
    assert '"/shops/{business_id}/provision"' in source
    assert '"/shops/{business_id}/provision/retry"' in source
    assert "Idempotency-Key" in source
    assert "provision_shop(" in source
    assert "schema_name" in source

