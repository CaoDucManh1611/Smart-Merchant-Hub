"""Retryable tenant-schema provisioning contracts."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database.bases import PlatformBase
from app.models.platform_control import PlatformBusiness, ProvisioningOperation, TenantRegistry
from app.tenancy.provisioning import provision_shop


def _platform_session():
    engine = create_engine("sqlite://")
    PlatformBase.metadata.create_all(engine)
    return engine, Session(engine)


def test_provision_shop_is_idempotent_and_activates_only_after_revision(monkeypatch):
    engine, db = _platform_session()
    try:
        db.add(PlatformBusiness(id=7, name="Seven", slug="seven"))
        db.commit()
        calls = []
        first = provision_shop(
            db,
            business_id=7,
            idempotency_key="provision:7",
            migrate=lambda schema: calls.append(schema) or "rev-1",
            revision_lookup=lambda _schema: "rev-1",
        )
        assert first.state == "active"
        assert first.feature_enabled is True
        repeated = provision_shop(
            db,
            business_id=7,
            idempotency_key="provision:7",
            migrate=lambda _schema: (_ for _ in ()).throw(AssertionError("must not rerun")),
        )
        assert repeated.id == first.id
        assert calls == ["shop_7"]
        assert db.scalar(select(ProvisioningOperation).where(ProvisioningOperation.idempotency_key == "provision:7")).state == "succeeded"
    finally:
        db.close()
        engine.dispose()


def test_provision_shop_keeps_schema_retryable_on_migration_failure(monkeypatch):
    engine, db = _platform_session()
    try:
        db.add(PlatformBusiness(id=8, name="Eight", slug="eight"))
        db.commit()
        try:
            provision_shop(
                db,
                business_id=8,
                idempotency_key="provision:8",
                migrate=lambda _schema: "",
                revision_lookup=lambda _schema: None,
            )
        except RuntimeError as exc:
            assert "tenant_revision_missing" in str(exc)
        else:
            raise AssertionError("provisioning must fail without a revision")
        registry = db.scalar(select(TenantRegistry).where(TenantRegistry.business_id == 8))
        operation = db.scalar(select(ProvisioningOperation).where(ProvisioningOperation.idempotency_key == "provision:8"))
        assert registry.state == "error"
        assert registry.feature_enabled is False
        assert operation.state == "failed"
        assert operation.last_error_code == "runtimeerror"
    finally:
        db.close()
        engine.dispose()
