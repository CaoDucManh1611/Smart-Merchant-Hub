"""Provider connection health checks with safe, tenant-local mutations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.platform_control import TenantRegistry
from app.services.channel_service import channel_credential_status, normalized_connection_state
from app.tenancy.schema import schema_name_for, validate_schema_name


def check_channel_health(
    db: Session,
    business_id: int,
    *,
    bot_probe: Callable[[Channel], bool] | None = None,
) -> list[dict]:
    """Refresh safe state for every channel in one shop.

    ``bot_probe`` is injected by the scheduler so tests and deployments can
    use provider-specific adapters without ever exposing a token here. Meta
    channels are checked locally from their expiry metadata; expired or
    revoked credentials are marked ``reconnect_required`` rather than
    silently falling back to an environment credential.
    """
    rows = db.scalars(
        select(Channel)
        .where(Channel.business_id == int(business_id))
        .order_by(Channel.channel_type.asc(), Channel.id.asc())
    ).all()
    output: list[dict] = []
    changed = False
    for channel in rows:
        state = normalized_connection_state(channel)
        if state == "connected" and channel.channel_type in {"telegram", "zalo"} and bot_probe is not None:
            try:
                if not bot_probe(channel):
                    state = "reconnect_required"
            except Exception:
                state = "error"
        if state == "reconnect_required" and channel.status == "active":
            channel.status = "reconnect_required"
            changed = True
        config = channel.config if isinstance(channel.config, dict) else {}
        output.append({
            "id": channel.id,
            "business_id": channel.business_id,
            "channel_type": channel.channel_type,
            "external_account_id": channel.external_account_id,
            "name": channel.name,
            "state": state,
            "credential": channel_credential_status(channel),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "webhook_status": "connected" if config.get("webhook_url") else "unknown",
        })
    if changed:
        db.commit()
    return output


def run_scheduled_channel_health(
    platform_db: Session,
    *,
    tenant_session_factory,
    bot_probes: dict[str, Callable[[Channel], bool]] | None = None,
) -> list[dict]:
    """Refresh provider state for every active, feature-enabled shop.

    The scheduler owns the cross-database loop; the per-shop checker remains
    tenant-local.  Registry values are validated before opening a session and
    a malformed/inactive entry is reported as an aggregate error rather than
    being used to select an arbitrary schema.  Results intentionally contain
    counts and bounded error codes only, so this function is safe to emit to
    worker logs or an operations dashboard.
    """
    registries = platform_db.scalars(
        select(TenantRegistry)
        .where(
            TenantRegistry.state == "active",
            TenantRegistry.feature_enabled.is_(True),
        )
        .order_by(TenantRegistry.business_id.asc())
    ).all()
    results: list[dict] = []
    for registry in registries:
        business_id = int(registry.business_id)
        try:
            schema = validate_schema_name(str(registry.schema_name))
            if schema != schema_name_for(business_id):
                raise PermissionError("tenant_schema_mismatch")
            probe = (bot_probes or {}).get("telegram")
            # A single probe may be supplied for both bot providers by a
            # deployment adapter.  A provider-specific map takes precedence.
            provider_probes = bot_probes or {}

            def probe_channel(channel: Channel) -> bool:
                callback = provider_probes.get(channel.channel_type) or probe
                return callback(channel) if callback is not None else True

            with tenant_session_factory(schema) as tenant_db:
                rows = check_channel_health(
                    tenant_db,
                    business_id,
                    bot_probe=probe_channel if provider_probes else None,
                )
            reconnect_required = sum(
                1 for row in rows if row.get("state") == "reconnect_required"
            )
            errors = sum(1 for row in rows if row.get("state") == "error")
            results.append(
                {
                    "business_id": business_id,
                    "schema_name": schema,
                    "status": "degraded" if reconnect_required or errors else "ok",
                    "channels_checked": len(rows),
                    "reconnect_required": reconnect_required,
                    "errors": errors,
                }
            )
        except Exception as exc:  # noqa: BLE001 - isolate one shop from the batch
            results.append(
                {
                    "business_id": business_id,
                    "schema_name": str(getattr(registry, "schema_name", "")),
                    "status": "error",
                    "channels_checked": 0,
                    "reconnect_required": 0,
                    "errors": 1,
                    "error_code": type(exc).__name__.lower().replace(" ", "_")[:80],
                }
            )
    return results


__all__ = ["check_channel_health", "run_scheduled_channel_health"]
