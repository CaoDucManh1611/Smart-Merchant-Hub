"""Lightweight load contracts for tenant webhook/RAG/worker boundaries."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services.crm_job_worker import TenantJobEnvelope, resolve_job_tenant


def test_worker_resolution_is_safe_under_concurrent_tenant_load():
    def resolve(business_id: int) -> str:
        envelope = TenantJobEnvelope(business_id, f"shop_{business_id}", business_id)
        return resolve_job_tenant(
            envelope,
            registry_lookup=lambda _id: type(
                "Registry",
                (),
                {"state": "active", "schema_name": f"shop_{business_id}"},
            )(),
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        schemas = list(pool.map(resolve, range(1, 65)))
    assert schemas == [f"shop_{business_id}" for business_id in range(1, 65)]


def test_load_sensitive_paths_keep_route_and_schema_boundaries():
    root = Path(__file__).resolve().parents[1] / "app"
    facebook = (root / "api" / "facebook.py").read_text(encoding="utf-8")
    retriever = (root / "rag" / "retriever.py").read_text(encoding="utf-8")
    worker = (root / "services" / "crm_job_worker.py").read_text(encoding="utf-8")
    assert "resolve_webhook_route" in facebook
    assert "tenant_session" in facebook
    assert "SessionLocal" not in facebook
    # Defense in depth: every hybrid-search path must retain an explicit shop
    # predicate even when the session is already bound to a tenant schema.
    assert retriever.count("d.business_id = :business_id") >= 2
    assert "TenantJobEnvelope" in worker
    assert "finally" in worker or "finally" in (root / "scripts" / "crm_job_worker.py").read_text(encoding="utf-8")
