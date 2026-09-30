from datetime import datetime
from decimal import Decimal

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
)
from app.services.quota_service import QuotaExceededError, quota_snapshot, reserve_quota


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
