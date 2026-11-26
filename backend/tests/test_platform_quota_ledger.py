from datetime import datetime
from decimal import Decimal
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database.bases import PlatformBase
from app.database.platform_session import PlatformSession
from app.models.platform_control import (
    PlatformBusiness,
    PlatformQuotaReservation,
    PlatformServicePlan,
    PlatformSubscription,
    PlatformUsage,
    TenantRegistry,
)
from app.services.quota_service import QuotaExceededError, quota_snapshot, reserve_quota
from app.models.document import Document


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    PlatformBase.metadata.create_all(engine)
    with PlatformSession(bind=engine) as session:
        session.add(PlatformBusiness(id=7, name="Shop 7", slug="shop-7"))
        plan = PlatformServicePlan(
            id=1,
            code="starter",
            name="Starter",
            price=Decimal("0"),
            quotas={"connected_channels": 1, "ai_calls": 2, "ai_cost": "10"},
        )
        session.add(plan)
        session.add(
            PlatformSubscription(
                business_id=7,
                plan_id=1,
                status="active",
                starts_at=datetime(2020, 1, 1),
            )
        )
        session.commit()
        yield session


def test_platform_usage_and_idempotency_use_control_plane_models(db):
    first = reserve_quota(
        db,
        7,
        "ai_calls",
        1,
        idempotency_key="rag-1",
        now=datetime(2026, 1, 1),
    )
    repeat = reserve_quota(
        db,
        7,
        "ai_calls",
        1,
        idempotency_key="rag-1",
        now=datetime(2026, 1, 1),
    )
    db.commit()
    assert first.used == repeat.used == Decimal("1")
    assert db.scalar(select(PlatformUsage).where(PlatformUsage.business_id == 7)).used == Decimal("1")
    assert db.scalar(select(PlatformQuotaReservation).where(PlatformQuotaReservation.business_id == 7)) is not None
    assert quota_snapshot(db, 7, now=datetime(2026, 1, 1))["resources"]["ai_calls"]["limit"] == 2

    with pytest.raises(QuotaExceededError):
        reserve_quota(db, 7, "ai_calls", 2, idempotency_key="rag-2", now=datetime(2026, 1, 1))


def test_snapshot_reads_restored_knowledge_inventory_without_resetting_ledger(db, monkeypatch):
    plan = db.get(PlatformServicePlan, 1)
    plan.quotas = {**plan.quotas, "documents": 3, "rag_chunks": 80}
    db.add(TenantRegistry(business_id=7, schema_name="tenant_7", state="active", feature_enabled=True))
    db.add(PlatformUsage(business_id=7, resource="documents", period_start=datetime(2026, 1, 1), used=2))
    db.add(PlatformUsage(business_id=7, resource="rag_chunks", period_start=datetime(2026, 1, 1), used=59))
    db.commit()
    tenant_engine = create_engine("sqlite://")
    Document.__table__.create(tenant_engine)
    with Session(tenant_engine) as tenant_db:
        tenant_db.info["tenant_schema"] = "tenant_7"
        tenant_db.add_all([
            Document(business_id=7, filename="active.md", file_type="md", status="ready", chunk_count=2),
            Document(business_id=7, filename="disabled.md", file_type="md", status="disabled", chunk_count=74),
            Document(business_id=7, filename="third.md", file_type="md", status="ready", chunk_count=1),
            Document(business_id=7, filename="deleted.md", file_type="md", status="deleted", chunk_count=99),
            Document(business_id=8, filename="other.md", file_type="md", status="ready", chunk_count=999),
        ])
        tenant_db.commit()

        @contextmanager
        def routed_session(schema):
            assert schema == "tenant_7"
            yield tenant_db

        monkeypatch.setattr("app.database.tenant_session.tenant_session", routed_session)
        snapshot = quota_snapshot(db, 7, now=datetime(2026, 1, 1))
    assert snapshot["resources"]["documents"]["used"] == 3
    assert snapshot["resources"]["rag_chunks"]["used"] == 77
    assert snapshot["resources"]["documents"]["percent"] == 100
    assert snapshot["resources"]["rag_chunks"]["near_limit"] is True
    assert snapshot["resources"]["rag_chunks"]["exceeded"] is False
    assert db.scalar(select(PlatformUsage).where(PlatformUsage.resource == "documents")).used == 2
    assert db.scalar(select(PlatformUsage).where(PlatformUsage.resource == "rag_chunks")).used == 59
