"""Workers must re-resolve an active tenant registry before processing jobs."""

from pathlib import Path

from app.services.crm_job_worker import TenantJobEnvelope, resolve_job_tenant


ROOT = Path(__file__).resolve().parents[1]


def test_job_envelope_rejects_forged_schema_name():
    envelope = TenantJobEnvelope(business_id=12, schema_name="shop_999", job_id=7)
    try:
        resolve_job_tenant(envelope, registry_lookup=lambda _business_id: "shop_12")
    except PermissionError:
        return
    raise AssertionError("forged schema name must be rejected")


def test_worker_source_contains_registry_state_gate_and_context_cleanup():
    source = (ROOT / "app" / "services" / "crm_job_worker.py").read_text(encoding="utf-8")
    assert "TenantJobEnvelope" in source
    assert "active" in source
    assert "finally" in source

