"""Persistent Meta integration configuration.

OAuth credentials are stored in app_settings so a successful connection is
available after a backend restart. Environment variables remain the fallback
for the existing single-shop/demo setup.
"""

from __future__ import annotations

from typing import Mapping

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.setting import AppSetting


META_KEYS = {
    "facebook_page_id": "meta.facebook_page_id",
    "facebook_page_name": "meta.facebook_page_name",
    "facebook_page_access_token": "meta.facebook_page_access_token",
    "instagram_account_id": "meta.instagram_account_id",
    "instagram_account_name": "meta.instagram_account_name",
    "meta_user_id": "meta.user_id",
    "meta_user_name": "meta.user_name",
    "connected_at": "meta.connected_at",
    "oauth_state": "meta.oauth_state",
    "oauth_state_created_at": "meta.oauth_state_created_at",
    "subscription_status": "meta.subscription_status",
}


def get_setting_value(key: str, default: str = "") -> str:
    try:
        with SessionLocal() as db:
            setting = db.get(AppSetting, key)
            if setting and setting.value:
                return setting.value
    except Exception:
        # Startup and webhook paths should still work from .env if the DB is
        # temporarily unavailable.
        pass
    return default


def save_settings(values: Mapping[str, str]) -> None:
    with SessionLocal() as db:
        for key, value in values.items():
            setting = db.get(AppSetting, key)
            if setting is None:
                db.add(AppSetting(key=key, value=str(value)))
            else:
                setting.value = str(value)
        db.commit()


def get_meta_config() -> dict[str, str]:
    return {
        "facebook_page_id": get_setting_value(
            META_KEYS["facebook_page_id"],
            settings.FACEBOOK_PAGE_ID,
        ),
        "facebook_page_name": get_setting_value(
            META_KEYS["facebook_page_name"],
        ),
        "facebook_page_access_token": get_setting_value(
            META_KEYS["facebook_page_access_token"],
            settings.FACEBOOK_PAGE_ACCESS_TOKEN,
        ),
        "instagram_account_id": get_setting_value(
            META_KEYS["instagram_account_id"],
            settings.INSTAGRAM_ACCOUNT_ID,
        ),
        "instagram_account_name": get_setting_value(
            META_KEYS["instagram_account_name"],
        ),
        "meta_user_id": get_setting_value(META_KEYS["meta_user_id"]),
        "meta_user_name": get_setting_value(META_KEYS["meta_user_name"]),
        "connected_at": get_setting_value(META_KEYS["connected_at"]),
        "subscription_status": get_setting_value(
            META_KEYS["subscription_status"],
        ),
    }


def save_meta_config(values: Mapping[str, str]) -> None:
    save_settings(
        {
            META_KEYS[key]: value
            for key, value in values.items()
            if key in META_KEYS and value is not None
        }
    )


def clear_meta_config() -> None:
    with SessionLocal() as db:
        for key in META_KEYS.values():
            setting = db.get(AppSetting, key)
            if setting is not None:
                db.delete(setting)
        db.commit()
