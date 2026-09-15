from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.bases import PlatformBase
from app.models.platform_control import PlatformBusiness, ProvisioningOperation, TenantRegistry
from app.tenancy import provisioning


class _Connection:
    pass


def _engine():
    engine = create_engine("sqlite://")
    PlatformBase.metadata.create_all(engine)
    return engine


def test_provisioning_is_idempotent_and_replay_does_not_migrate_twice(monkeypatch):
    engine = _engine()
    calls = []

    @contextmanager
    def connect():
        yield _Connection()

    monkeypatch.setattr(provisioning, "upgrade_tenant_schema", lambda conn, schema: calls.append(schema) or "20260915_0001")
    monkeypatch.setattr(provisioning, "current_tenant_revision", lambda conn, schema: "20260915_0001")
    with Session(engine) as db:
        db.add(PlatformBusiness(id=7, name="Shop", slug="shop-7"))
        db.commit()
        first = provisioning.provision_shop(db, business_id=7, idempotency_key="req-7", tenant_connect=connect)
        second = provisioning.provision_shop(db, business_id=7, idempotency_key="req-7", tenant_connect=connect)
        assert first.state == second.state == "active"
        assert first.schema_name == "shop_7"
        assert calls == ["shop_7"]
        assert db.query(ProvisioningOperation).count() == 1


def test_failed_provisioning_is_retryable_and_never_drops_schema(monkeypatch):
    engine = _engine()
    attempts = {"count": 0}

    @contextmanager
    def connect():
        yield _Connection()

    def migrate(_conn, _schema):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("private database details")
        return "20260915_0001"

    monkeypatch.setattr(provisioning, "upgrade_tenant_schema", migrate)
    monkeypatch.setattr(provisioning, "current_tenant_revision", lambda conn, schema: "20260915_0001")
    with Session(engine) as db:
        db.add(PlatformBusiness(id=8, name="Retry", slug="shop-8"))
        db.commit()
        failed = provisioning.provision_shop(db, business_id=8, idempotency_key="req-8", tenant_connect=connect)
        assert failed.state == "provision_failed"
        assert failed.feature_enabled is False
        assert failed.migration_error == "tenant_migration_failed"
        retried = provisioning.retry_provision_shop(db, business_id=8, idempotency_key="req-8", tenant_connect=connect)
        assert retried.state == "active"
        assert retried.tenant_revision == "20260915_0001"
        assert db.query(TenantRegistry).one().schema_name == "shop_8"

