from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

import app.api.support as support_api
import app.models  # noqa: F401 - register tenant relationships for SQLite metadata
from app.database.bases import PlatformBase, TenantBase
from app.database.platform_session import get_platform_db
from app.models.channel import Channel, ChannelEvent
from app.models.platform_control import PlatformBusiness, PlatformUser
from app.services.support_access import create_support_grant, issue_support_token


def test_failed_channel_event_can_be_retried_once_with_shop_scope(monkeypatch):
    engine_options = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }
    platform_engine = create_engine("sqlite://", **engine_options)
    PlatformBase.metadata.create_all(platform_engine)
    tenant_engines = {
        7: create_engine("sqlite://", **engine_options),
        8: create_engine("sqlite://", **engine_options),
    }
    for engine in tenant_engines.values():
        TenantBase.metadata.create_all(engine)

    with Session(platform_engine) as platform_db:
        for business_id in (7, 8):
            platform_db.add(PlatformBusiness(id=business_id, name=f"Shop {business_id}", slug=f"shop-{business_id}"))
        platform_db.add_all([
            PlatformUser(id=10, business_id=7, email="owner7@example.test", full_name="Owner 7", role="owner"),
            PlatformUser(id=11, business_id=8, email="owner8@example.test", full_name="Owner 8", role="owner"),
            PlatformUser(id=20, business_id=None, email="support@example.test", full_name="Support", role="support"),
        ])
        platform_db.commit()
        tokens = {}
        for business_id, owner_id in ((7, 10), (8, 11)):
            grant = create_support_grant(
                platform_db,
                business_id=business_id,
                granted_by_user_id=owner_id,
                support_user_id=20,
                reason="Retry failed channel delivery",
                scopes=["channels:retry"],
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=20),
            )
            platform_db.commit()
            tokens[business_id] = issue_support_token(
                platform_db,
                grant_id=grant.id,
                support_user_id=20,
            )[0]

    tenant_db = Session(tenant_engines[7])
    tenant_db.add(Channel(
        id=41,
        business_id=7,
        channel_type="facebook",
        name="Test page",
        external_account_id="page-7",
        status="active",
    ))
    tenant_db.add(ChannelEvent(
        id=51,
        channel_id=41,
        event_type="message",
        external_event_id="fb-retry-mid",
        payload={
            "sender": {"id": "synthetic-customer"},
            "recipient": {"id": "page-7"},
            "message": {"mid": "fb-retry-mid", "text": "synthetic payload"},
        },
        status="failed",
    ))
    tenant_db.commit()

    @contextmanager
    def isolated_tenant_session(schema_name):
        business_id = int(str(schema_name).removeprefix("shop_"))
        with Session(tenant_engines[business_id]) as tenant_session:
            yield tenant_session

    processed = []

    def fake_process_and_save_message(*, db, message):
        processed.append(message["external_message_id"])
        return {
            "_created": True,
            "business_id": message["business_id"],
            "conversation_id": 3,
            "message_id": 99,
        }

    async def no_broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr(support_api, "tenant_session", isolated_tenant_session)
    monkeypatch.setattr(support_api, "process_and_save_message", fake_process_and_save_message)
    monkeypatch.setattr(support_api.manager, "broadcast", no_broadcast)

    def override_platform_db():
        with Session(platform_engine) as session:
            yield session

    app = FastAPI()
    app.include_router(support_api.router, prefix="/api")
    app.dependency_overrides[get_platform_db] = override_platform_db
    try:
        client = TestClient(app)
        route = "/api/support/channel-events/51/retry"
        first = client.post(route, headers={"Authorization": f"Bearer {tokens[7]}"})
        assert first.status_code == 200, first.text
        assert first.json() == {"event_id": 51, "status": "processed", "messages_created": 1}
        assert processed == ["fb-retry-mid"]

        duplicate = client.post(route, headers={"Authorization": f"Bearer {tokens[7]}"})
        assert duplicate.status_code == 409
        assert processed == ["fb-retry-mid"]

        other_shop = client.post(route, headers={"Authorization": f"Bearer {tokens[8]}"})
        assert other_shop.status_code == 404
        assert processed == ["fb-retry-mid"]
    finally:
        app.dependency_overrides.clear()
        tenant_db.close()
        platform_engine.dispose()
        for engine in tenant_engines.values():
            engine.dispose()
