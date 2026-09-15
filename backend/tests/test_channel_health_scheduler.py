from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.bases import PlatformBase, TenantBase
from app.models.channel import Channel
from app.models.platform_control import PlatformBusiness, TenantRegistry
from app.services.channel_health import run_scheduled_channel_health


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_scheduled_health_isolates_each_active_shop_and_returns_aggregates():
    platform_engine = _engine()
    tenant_engine = _engine()
    PlatformBase.metadata.create_all(platform_engine)
    TenantBase.metadata.create_all(tenant_engine)
    try:
        with Session(platform_engine) as platform_db, Session(tenant_engine) as tenant_db:
            platform_db.add_all(
                [
                    PlatformBusiness(id=11, name="One", slug="one"),
                    PlatformBusiness(id=12, name="Two", slug="two"),
                    TenantRegistry(
                        business_id=11,
                        schema_name="shop_11",
                        state="active",
                        feature_enabled=True,
                    ),
                    TenantRegistry(
                        business_id=12,
                        schema_name="shop_12",
                        state="ready",
                        feature_enabled=False,
                    ),
                ]
            )
            tenant_db.add_all(
                [
                    Channel(
                        id=1,
                        business_id=11,
                        channel_type="telegram",
                        external_account_id="bot-11",
                        name="Bot 11",
                        access_token_encrypted="ciphertext",
                    ),
                    Channel(
                        id=2,
                        business_id=11,
                        channel_type="facebook",
                        external_account_id="page-11",
                        name="Page 11",
                        access_token_encrypted="ciphertext",
                        config={
                            "token_expires_at": (
                                datetime.now(timezone.utc) - timedelta(minutes=1)
                            ).isoformat()
                        },
                    ),
                    Channel(
                        id=3,
                        business_id=12,
                        channel_type="telegram",
                        external_account_id="bot-12",
                        name="Bot 12",
                        access_token_encrypted="ciphertext",
                    ),
                ]
            )
            platform_db.commit()
            tenant_db.commit()

            @contextmanager
            def tenant_factory(_schema):
                with Session(tenant_engine) as db:
                    yield db

            results = run_scheduled_channel_health(
                platform_db,
                tenant_session_factory=tenant_factory,
                bot_probes={"telegram": lambda _channel: False},
            )

            assert results == [
                {
                    "business_id": 11,
                    "schema_name": "shop_11",
                    "status": "degraded",
                    "channels_checked": 2,
                    "reconnect_required": 2,
                    "errors": 0,
                }
            ]
            tenant_db.expire_all()
            assert tenant_db.get(Channel, 1).status == "reconnect_required"
            assert tenant_db.get(Channel, 2).status == "reconnect_required"
            assert tenant_db.get(Channel, 3).status == "active"
    finally:
        tenant_engine.dispose()
        platform_engine.dispose()


def test_scheduled_health_rejects_mismatched_registry_schema_without_opening_tenant():
    platform_engine = _engine()
    PlatformBase.metadata.create_all(platform_engine)
    try:
        with Session(platform_engine) as platform_db:
            platform_db.add(
                PlatformBusiness(id=13, name="Three", slug="three")
            )
            platform_db.add(
                TenantRegistry(
                    business_id=13,
                    schema_name="shop_999",
                    state="active",
                    feature_enabled=True,
                )
            )
            platform_db.commit()
            opened = []

            @contextmanager
            def tenant_factory(_schema):
                opened.append(True)
                raise AssertionError("mismatched registry must not open tenant DB")
                yield  # pragma: no cover

            results = run_scheduled_channel_health(
                platform_db,
                tenant_session_factory=tenant_factory,
            )
            assert results[0]["status"] == "error"
            assert results[0]["error_code"] == "permissionerror"
            assert opened == []
    finally:
        platform_engine.dispose()
