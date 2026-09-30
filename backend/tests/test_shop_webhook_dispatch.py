"""Contract tests for the shop-slug webhook dispatcher.

The provider-specific adapters have their own coverage.  These tests keep the
public ``/api/webhooks/{shop_slug}`` boundary honest: an unknown secret is
rejected, while a registered secret is dispatched to the matching adapter for
the matching shop only.
"""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.bases import PlatformBase
from app.database.platform_session import get_platform_db
from app.main import app
from app.models.platform_control import PlatformBusiness, TenantRegistry
from app.tenancy.registry import register_webhook_route


def _engine():
    return create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


def test_shop_slug_dispatch_rejects_wrong_secret_and_dispatches_telegram_and_zalo():
    engine = _engine()
    PlatformBase.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(PlatformBusiness(id=901, name="Webhook Shop", slug="webhook-shop"))
        db.add(TenantRegistry(
            business_id=901,
            schema_name="shop_901",
            state="active",
            feature_enabled=True,
        ))
        db.flush()
        register_webhook_route(
            db,
            provider="telegram",
            external_account_id="tg-901",
            webhook_secret="tg-secret-901",
            business_id=901,
            schema_name="shop_901",
            channel_id=1,
        )
        register_webhook_route(
            db,
            provider="zalo",
            external_account_id="zalo-901",
            webhook_secret="zalo-secret-901",
            business_id=901,
            schema_name="shop_901",
            channel_id=2,
        )
        db.commit()

    def override_platform_db():
        with Session(engine) as db:
            yield db

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_platform_db] = override_platform_db
    try:
        client = TestClient(app)
        telegram_payload = {"update_id": 1}
        wrong_telegram = client.post(
            "/api/webhooks/webhook-shop",
            json=telegram_payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
        )
        assert wrong_telegram.status_code == 401

        with patch("app.api.webhooks.receive_telegram_webhook", new=AsyncMock(return_value={"status": "received"})) as telegram_handler:
            telegram = client.post(
                "/api/webhooks/webhook-shop",
                json=telegram_payload,
                headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret-901"},
            )
        assert telegram.status_code == 200
        telegram_handler.assert_awaited_once()

        wrong_zalo = client.post(
            "/api/webhooks/webhook-shop",
            json={"oa_id": "zalo-901"},
            headers={"X-Bot-Api-Secret-Token": "wrong-secret"},
        )
        assert wrong_zalo.status_code == 401

        with patch("app.api.webhooks.receive_zalo_webhook", new=AsyncMock(return_value={"status": "received"})) as zalo_handler:
            zalo = client.post(
                "/api/webhooks/webhook-shop",
                json={"oa_id": "zalo-901"},
                headers={"X-Bot-Api-Secret-Token": "zalo-secret-901"},
            )
        assert zalo.status_code == 200
        zalo_handler.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        engine.dispose()
