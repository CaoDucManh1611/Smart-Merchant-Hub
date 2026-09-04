"""Controlled, idempotent migration of legacy global channel credentials."""

from collections.abc import Mapping

from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.channel_migration import ChannelMigrationAudit
from app.models.setting import AppSetting
from app.core.config import settings
from app.services.channel_service import upsert_channel_connection


def _settings(db: Session) -> dict[str, str]:
    return {row.key: row.value for row in db.query(AppSetting).all()}


def migrate_legacy_channels(
    db: Session,
    *,
    mapping: Mapping[str, int],
    encryption_key: str,
) -> dict:
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
                channel = upsert_channel_connection(
                    db,
                    business_id=int(business_id),
                    channel_type=channel_type,
                    external_account_id=account_id,
                    name=str(name or account_id),
                    access_token=str(token),
                    encryption_key=encryption_key,
                )
                item.update({"status": "migrated", "business_id": business_id, "channel_id": channel.id})
            except (PermissionError, ValueError, LookupError) as exc:
                item["reason"] = str(exc)
        db.add(ChannelMigrationAudit(
            source="app_settings",
            channel_type=channel_type,
            external_account_id=account_id,
            business_id=item.get("business_id"),
            status=item["status"],
            reason=item.get("reason"),
            report=item,
        ))
        db.commit()
        items.append(item)
    return {"items": items, "migrated": sum(i["status"] == "migrated" for i in items), "skipped": sum(i["status"] == "skipped" for i in items)}
