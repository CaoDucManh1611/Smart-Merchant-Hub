"""Controlled, idempotent migration of legacy global channel credentials."""

from collections.abc import Mapping

from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.channel_migration import ChannelMigrationAudit
from app.models.setting import AppSetting
from app.core.config import settings
from app.database.tenant_session import tenant_session
from app.services.channel_service import upsert_channel_connection
from app.services.quota_service import reserve_quota
from app.tenancy.registry import register_webhook_route
from app.tenancy.schema import schema_name_for


def _settings(db: Session) -> dict[str, str]:
    return {row.key: row.value for row in db.query(AppSetting).all()}


def migrate_legacy_channels(
    db: Session,
    *,
    mapping: Mapping[str, int],
    encryption_key: str,
    platform_db: Session | None = None,
) -> dict:
    """Copy explicitly mapped legacy Meta credentials into shop schemas.

    The source session is read-only.  A missing mapping is reported as
    skipped, never guessed from a default business.  ``platform_db`` is
    optional for the development importer; production callers must provide it
    so quota and webhook route records are coordinated.
    """
    values = _settings(db)
    candidates = [
        ("facebook", values.get("meta.facebook_page_id") or settings.FACEBOOK_PAGE_ID, values.get("meta.facebook_page_name"), values.get("meta.facebook_page_access_token") or settings.FACEBOOK_PAGE_ACCESS_TOKEN),
        (
            "instagram",
            values.get("meta.instagram_account_id") or settings.INSTAGRAM_ACCOUNT_ID,
            values.get("meta.instagram_account_name"),
            values.get("meta.instagram_access_token") or settings.INSTAGRAM_ACCESS_TOKEN,
        ),
    ]
    items = []
    for channel_type, account_id, name, token in candidates:
        if not account_id and not token:
            continue
        account_id = str(account_id or "").strip()
        key = f"{channel_type}:{account_id}"
        item = {"channel_type": channel_type, "external_account_id": account_id, "status": "skipped"}
        business_id = mapping.get(key)
        if not account_id or not token:
            item["reason"] = "missing legacy account id or token"
        elif business_id is None:
            item["reason"] = "explicit business mapping is required"
        else:
            try:
                with tenant_session(schema_name_for(int(business_id))) as tenant_db:
                    channel = upsert_channel_connection(
                        tenant_db,
                        business_id=int(business_id),
                        channel_type=channel_type,
                        external_account_id=account_id,
                        name=str(name or account_id),
                        access_token=str(token),
                        encryption_key=encryption_key,
                        reserve_channel_slot=(
                            (lambda: reserve_quota(platform_db, int(business_id), "connected_channels"))
                            if platform_db is not None
                            else (lambda: None)
                        ),
                    )
                    if platform_db is not None:
                        register_webhook_route(
                            platform_db,
                            provider=channel_type,
                            external_account_id=account_id,
                            webhook_secret=None,
                            business_id=int(business_id),
                            schema_name=schema_name_for(int(business_id)),
                            channel_id=channel.id,
                        )
                    tenant_db.add(ChannelMigrationAudit(
                        source="app_settings",
                        channel_type=channel_type,
                        external_account_id=account_id,
                        business_id=int(business_id),
                        status="migrated",
                        reason=None,
                        report={"channel_type": channel_type, "external_account_id": account_id},
                    ))
                item.update({"status": "migrated", "business_id": business_id, "channel_id": channel.id})
            except (PermissionError, ValueError, LookupError) as exc:
                item["reason"] = str(exc)
        if item["status"] == "skipped":
            mapped_business = item.get("business_id")
            if mapped_business:
                with tenant_session(schema_name_for(int(mapped_business))) as tenant_db:
                    tenant_db.add(ChannelMigrationAudit(
                        source="app_settings",
                        channel_type=channel_type,
                        external_account_id=account_id,
                        business_id=int(mapped_business),
                        status="skipped",
                        reason=item.get("reason"),
                        report=item,
                    ))
            else:
                # Keep the source read-only; a skipped row is returned in the
                # report when no tenant mapping exists.
                pass
        if platform_db is not None:
            platform_db.commit()
        items.append(item)
    return {"items": items, "migrated": sum(i["status"] == "migrated" for i in items), "skipped": sum(i["status"] == "skipped" for i in items)}
