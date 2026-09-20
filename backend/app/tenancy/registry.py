"""Platform route registry for provider webhooks.

The registry stores only keyed digests. A webhook can be routed with one
indexed lookup and never needs to scan tenant ``channels`` rows or decrypt a
credential in the request path.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.channel_route import ChannelRoute
from app.models.platform_control import TenantRegistry
from app.tenancy.schema import schema_name_for, validate_schema_name


@dataclass(frozen=True)
class WebhookRoute:
    business_id: int
    schema_name: str
    channel_id: int


def _key(secret: str | None = None) -> bytes:
    value = str(secret or getattr(settings, "CHANNEL_ROUTE_SECRET", "") or "").strip()
    if not value:
        # Local/demo environments may reuse the development auth secret so
        # onboarding remains usable without weakening production validation.
        if str(getattr(settings, "ENVIRONMENT", "development")).strip().lower() != "production":
            value = str(getattr(settings, "AUTH_SECRET", "") or "dev-route-secret").strip()
        else:
            raise RuntimeError("CHANNEL_ROUTE_SECRET is required for webhook routing")
    return value.encode("utf-8")


def hash_route_key(route_key: str, *, secret: str | None = None) -> str:
    return hmac.new(_key(secret), str(route_key).encode("utf-8"), hashlib.sha256).hexdigest()


def hash_webhook_secret(webhook_secret: str, *, secret: str | None = None) -> str:
    return hash_route_key(webhook_secret, secret=secret)


def register_webhook_route(
    platform_db: Session,
    *,
    provider: str,
    external_account_id: str,
    webhook_secret: str | None,
    business_id: int,
    schema_name: str | None = None,
    channel_id: int | None = None,
    route_secret: str | None = None,
) -> ChannelRoute:
    """Create or update one globally unique provider route idempotently."""
    provider_name = str(provider).strip().lower()
    if provider_name not in {"telegram", "zalo", "facebook", "instagram"}:
        raise ValueError("Unsupported webhook provider")
    resolved_schema = validate_schema_name(schema_name or schema_name_for(business_id))
    account_hash = hash_route_key(external_account_id, secret=route_secret)
    secret_hash = hash_webhook_secret(webhook_secret, secret=route_secret) if webhook_secret else None
    account_route = platform_db.scalar(
        select(ChannelRoute).where(
            ChannelRoute.provider == provider_name,
            ChannelRoute.external_account_id_hash == account_hash,
        )
    )
    secret_route = None
    if secret_hash:
        secret_route = platform_db.scalar(
            select(ChannelRoute).where(
                ChannelRoute.provider == provider_name,
                ChannelRoute.secret_hash == secret_hash,
            )
        )
    if account_route is not None and account_route.business_id != int(business_id):
        raise PermissionError("Provider account is already connected to another shop")
    if secret_route is not None and secret_route.business_id != int(business_id):
        raise PermissionError("Webhook secret is already connected to another shop")
    if account_route is not None and secret_route is not None and account_route.id != secret_route.id:
        raise PermissionError("Webhook route is ambiguous; rotate the provider connection")
    route = account_route or secret_route
    if route is None:
        route = ChannelRoute(
            provider=provider_name,
            external_account_id_hash=account_hash,
            business_id=int(business_id),
            schema_name=resolved_schema,
        )
        platform_db.add(route)
    route.secret_hash = secret_hash
    route.schema_name = resolved_schema
    route.channel_id = int(channel_id) if channel_id is not None else route.channel_id
    route.status = "active"
    platform_db.flush()
    return route


def resolve_webhook_route(
    platform_db: Session,
    provider: str,
    route_key: str,
    *,
    route_secret: str | None = None,
) -> WebhookRoute | None:
    """Resolve a route by keyed hash and reject inactive/forged schemas."""
    provider_name = str(provider).strip().lower()
    account_hash = hash_route_key(route_key, secret=route_secret)
    try:
        matches = platform_db.scalars(
            select(ChannelRoute).where(
                ChannelRoute.provider == provider_name,
                ChannelRoute.status == "active",
                or_(
                    ChannelRoute.external_account_id_hash == account_hash,
                    ChannelRoute.secret_hash == account_hash,
                ),
            )
        ).all()
    except Exception:
        # Old local/test databases can predate the route-registry migration.
        # Production must fail closed so a webhook is never routed by scanning
        # tenant content or guessing a default shop.
        if str(getattr(settings, "ENVIRONMENT", "development")).strip().lower() == "production":
            raise
        platform_db.rollback()
        matches = []
    # A route key must map to exactly one shop.  Treat a hash collision or a
    # malformed registry with multiple matches as unknown rather than
    # guessing which tenant should receive a webhook.
    if len(matches) != 1:
        # Development and test installs may still have tenant ``channels``
        # rows from before the platform route registry was introduced. Keep a
        # compatibility path that is strictly disabled in production; a
        # production webhook must always resolve through the keyed registry.
        if str(getattr(settings, "ENVIRONMENT", "development")).strip().lower() != "production":
            try:
                from app.models.channel import Channel

                legacy_channels = platform_db.scalars(
                    select(Channel).where(
                        Channel.channel_type == provider_name,
                        Channel.status == "active",
                    )
                ).all()
                # Older local fixtures stored the webhook secret in the
                # tenant channel JSON instead of the global route registry.
                # Accept that form only outside production; production keeps
                # the indexed, hashed registry as its sole routing source.
                legacy_channel = next(
                    (
                        channel
                        for channel in legacy_channels
                        if channel.external_account_id == str(route_key)
                        or (
                            isinstance(channel.config, dict)
                            and channel.config.get("webhook_secret") == str(route_key)
                        )
                    ),
                    None,
                )
            except Exception:
                legacy_channel = None
            if legacy_channel is not None:
                return WebhookRoute(
                    business_id=int(legacy_channel.business_id),
                    schema_name=schema_name_for(int(legacy_channel.business_id)),
                    channel_id=int(legacy_channel.id),
                )
        return None
    route = matches[0]
    schema = validate_schema_name(route.schema_name)
    if schema != schema_name_for(int(route.business_id)):
        return None
    if not route.channel_id:
        return None
    # A cutover marks the registry as ``migrating`` and disables the feature
    # before any copy starts. Do not deliver new webhook events while that
    # maintenance window is open; rollback can safely re-enable the route.
    # Local databases created before the registry migration may have no row, so
    # retain their development compatibility path. Production fails closed.
    try:
        registry = platform_db.scalar(
            select(TenantRegistry).where(
                TenantRegistry.business_id == int(route.business_id)
            )
        )
    except Exception:
        if str(getattr(settings, "ENVIRONMENT", "development")).strip().lower() == "production":
            raise
        registry = None
    if registry is None:
        if str(getattr(settings, "ENVIRONMENT", "development")).strip().lower() == "production":
            return None
    elif (
        registry.state != "active"
        or not bool(registry.feature_enabled)
        or validate_schema_name(str(registry.schema_name)) != schema
    ):
        return None
    return WebhookRoute(
        business_id=int(route.business_id),
        schema_name=schema,
        channel_id=int(route.channel_id or 0),
    )


def deactivate_webhook_route(
    platform_db: Session,
    *,
    provider: str,
    external_account_id: str,
    route_secret: str | None = None,
) -> bool:
    route = platform_db.scalar(
        select(ChannelRoute).where(
            ChannelRoute.provider == str(provider).strip().lower(),
            or_(
                ChannelRoute.external_account_id_hash == hash_route_key(external_account_id, secret=route_secret),
                ChannelRoute.secret_hash == hash_route_key(external_account_id, secret=route_secret),
            ),
        )
    )
    if route is None:
        return False
    route.status = "inactive"
    platform_db.flush()
    return True


def deactivate_route_for_channel(platform_db: Session, channel_id: int) -> bool:
    """Deactivate a route without needing to recover a provider secret."""
    route = platform_db.scalar(select(ChannelRoute).where(ChannelRoute.channel_id == int(channel_id)))
    if route is None:
        return False
    route.status = "inactive"
    platform_db.flush()
    return True

