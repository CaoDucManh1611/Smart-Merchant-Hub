"""Global webhook route contracts for provider-account and secret hashes."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.bases import PlatformBase
from app.models.platform_control import PlatformBusiness  # noqa: F401
from app.tenancy.registry import (
    hash_route_key,
    register_webhook_route,
    resolve_webhook_route,
)


def _engine():
    return create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


def test_secret_routes_resolve_without_scanning_tenant_channels(monkeypatch):
    engine = _engine()
    PlatformBase.metadata.create_all(engine)
    monkeypatch.setattr("app.tenancy.registry.settings.CHANNEL_ROUTE_SECRET", "route-test-secret")
    with Session(engine) as db:
        route = register_webhook_route(
            db,
            provider="telegram",
            external_account_id="bot-42",
            webhook_secret="secret-42",
            business_id=42,
            channel_id=7,
        )
        db.commit()
        resolved = resolve_webhook_route(db, "telegram", "secret-42")
        assert resolved is not None
        assert resolved.business_id == 42
        assert resolved.schema_name == "shop_42"
        assert resolved.channel_id == 7
        assert route.external_account_id_hash == hash_route_key("bot-42", secret="route-test-secret")


def test_same_provider_account_cannot_be_registered_for_two_shops(monkeypatch):
    engine = _engine()
    PlatformBase.metadata.create_all(engine)
    monkeypatch.setattr("app.tenancy.registry.settings.CHANNEL_ROUTE_SECRET", "route-test-secret")
    with Session(engine) as db:
        register_webhook_route(
            db,
            provider="zalo",
            external_account_id="oa-42",
            webhook_secret="secret-a",
            business_id=42,
            channel_id=1,
        )
        db.commit()
        try:
            register_webhook_route(
                db,
                provider="zalo",
                external_account_id="oa-42",
                webhook_secret="secret-b",
                business_id=99,
                channel_id=2,
            )
        except PermissionError:
            return
    raise AssertionError("a provider account must be globally unique")
