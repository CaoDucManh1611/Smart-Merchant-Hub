"""Tenant-scoped Meta display configuration.

Provider credentials are owned by the tenant ``channels`` table. This module
only reads non-secret display settings from the active shop session; there is
no process-wide global settings or environment-token fallback in the runtime path.
Callers obtain that session through the ``get_tenant_db`` dependency.
"""

from __future__ import annotations

from typing import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.business_setting import BusinessSetting


META_KEYS = {
    "facebook_page_id": "meta.facebook_page_id",
    "facebook_page_name": "meta.facebook_page_name",
    "instagram_account_id": "meta.instagram_account_id",
    "instagram_account_name": "meta.instagram_account_name",
    "meta_user_id": "meta.user_id",
    "meta_user_name": "meta.user_name",
    "connected_at": "meta.connected_at",
    "subscription_status": "meta.subscription_status",
}


def _tenant_value(db: Session | None, business_id: int | None, key: str, default: str = "") -> str:
    if db is None or business_id is None:
        return default
    row = db.scalar(
        select(BusinessSetting).where(
            BusinessSetting.business_id == int(business_id),
            BusinessSetting.key == key,
        )
    )
    return str(row.value) if row is not None and row.value else default


def get_setting_value(
    key: str,
    default: str = "",
    *,
    db: Session | None = None,
    business_id: int | None = None,
) -> str:
    """Read a tenant setting; missing tenant context fails closed."""
    return _tenant_value(db, business_id, key, default)


def save_settings(db: Session, business_id: int, values: Mapping[str, str]) -> None:
    """Upsert display settings in the current shop schema."""
    for key, value in values.items():
        row = db.scalar(
            select(BusinessSetting).where(
                BusinessSetting.business_id == int(business_id),
                BusinessSetting.key == key,
            )
        )
        if row is None:
            db.add(BusinessSetting(business_id=int(business_id), key=key, value=str(value)))
        else:
            row.value = str(value)
    db.flush()


def get_meta_config(db: Session | None = None, business_id: int | None = None) -> dict[str, str]:
    """Return safe Meta display metadata for one shop.

    The access-token field is always empty. Callers that send through Meta
    must load and decrypt the matching tenant ``Channel`` row.
    """
    return {
        # A missing tenant session must never fall back to process-wide
        # provider identities.  The caller should fail closed and ask the
        # shop to reconnect instead of sending through another shop's page.
        "facebook_page_id": _tenant_value(db, business_id, META_KEYS["facebook_page_id"]),
        "facebook_page_name": _tenant_value(db, business_id, META_KEYS["facebook_page_name"]),
        "facebook_page_access_token": "",
        "instagram_account_id": _tenant_value(db, business_id, META_KEYS["instagram_account_id"]),
        "instagram_account_name": _tenant_value(db, business_id, META_KEYS["instagram_account_name"]),
        "meta_user_id": _tenant_value(db, business_id, META_KEYS["meta_user_id"]),
        "meta_user_name": _tenant_value(db, business_id, META_KEYS["meta_user_name"]),
        "connected_at": _tenant_value(db, business_id, META_KEYS["connected_at"]),
        "subscription_status": _tenant_value(db, business_id, META_KEYS["subscription_status"]),
    }


def save_meta_config(db: Session, business_id: int, values: Mapping[str, str]) -> None:
    """Persist only non-secret Meta display values for one shop."""
    save_settings(
        db,
        business_id,
        {
            META_KEYS[key]: value
            for key, value in values.items()
            if key in META_KEYS and value is not None
        },
    )


def clear_meta_config(db: Session, business_id: int) -> None:
    """Remove display settings for one shop; channel credentials are separate."""
    rows = db.scalars(
        select(BusinessSetting).where(
            BusinessSetting.business_id == int(business_id),
            BusinessSetting.key.in_(tuple(META_KEYS.values())),
        )
    ).all()
    for row in rows:
        db.delete(row)
    db.flush()
