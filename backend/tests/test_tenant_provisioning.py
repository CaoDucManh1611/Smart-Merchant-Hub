from contextlib import contextmanager

import pytest
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


def test_successful_operation_reconciles_a_stale_registry(monkeypatch):
    engine = _engine()
    calls = []

    @contextmanager
    def connect():
        yield _Connection()

    monkeypatch.setattr(provisioning, "upgrade_tenant_schema", lambda conn, schema: calls.append(schema) or "20260915_0001")
    monkeypatch.setattr(provisioning, "current_tenant_revision", lambda conn, schema: "20260915_0001")
    with Session(engine) as db:
        db.add(PlatformBusiness(id=9, name="Stale", slug="stale-9"))
        db.commit()
        first = provisioning.provision_shop(db, business_id=9, idempotency_key="req-9", tenant_connect=connect)
        first.state = "provisioning"
        first.feature_enabled = False
        db.commit()

        repaired = provisioning.provision_shop(db, business_id=9, idempotency_key="req-9", tenant_connect=connect)

        assert repaired.state == "active"
        assert repaired.feature_enabled is True
        assert calls == ["shop_9", "shop_9"]


def test_default_tenant_migration_commits_before_activating_shop(monkeypatch):
    engine = _engine()
    events = []

    @contextmanager
    def begin():
        events.append("begin")
        try:
            yield _Connection()
        except Exception:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    monkeypatch.setattr(provisioning.tenant_engine, "begin", begin)

    def migrate(_connection, _schema):
        events.append("migrate")
        return "20260926_0007"

    monkeypatch.setattr(provisioning, "upgrade_tenant_schema", migrate)
    monkeypatch.setattr(provisioning, "current_tenant_revision", lambda _connection, _schema: "20260926_0007")
    with Session(engine) as db:
        db.add(PlatformBusiness(id=12, name="Transaction", slug="shop-12"))
        db.commit()
        registry = provisioning.provision_shop(db, business_id=12, idempotency_key="transaction-12")

        assert events == ["begin", "migrate", "commit"]
        assert registry.state == "active"
        assert registry.tenant_revision == "20260926_0007"


def test_provisioning_rejects_invalid_identity_and_cross_shop_idempotency_reuse(monkeypatch):
    engine = _engine()

    @contextmanager
    def connect():
        yield _Connection()

    monkeypatch.setattr(provisioning, "upgrade_tenant_schema", lambda _conn, _schema: "20260915_0001")
    monkeypatch.setattr(provisioning, "current_tenant_revision", lambda _conn, _schema: "20260915_0001")
    with Session(engine) as db:
        db.add_all([
            PlatformBusiness(id=10, name="First", slug="first-10"),
            PlatformBusiness(id=11, name="Second", slug="second-11"),
        ])
        db.commit()
        provisioning.provision_shop(db, business_id=10, idempotency_key="shared-request", tenant_connect=connect)
        with pytest.raises(provisioning.ProvisioningValidationError):
            provisioning.provision_shop(db, business_id=11, idempotency_key="shared-request", tenant_connect=connect)
        for invalid_id in (0, -1, "not-a-number"):
            with pytest.raises(provisioning.ProvisioningValidationError):
                provisioning.provision_shop(db, business_id=invalid_id, idempotency_key="valid-request", tenant_connect=connect)
