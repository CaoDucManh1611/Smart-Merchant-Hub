"""Meta OAuth connection flow for Facebook Pages and linked Instagram."""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.services.meta_config_service import (
    META_KEYS,
    clear_meta_config,
    get_meta_config,
    get_setting_value,
    save_meta_config,
    save_settings,
)


router = APIRouter()


def _redirect_uri() -> str:
    configured = settings.META_OAUTH_REDIRECT_URI.strip()
    if configured:
        return configured

    public_base_url = settings.PUBLIC_BASE_URL.strip().rstrip("/")
    if not public_base_url:
        raise HTTPException(
            status_code=500,
            detail="PUBLIC_BASE_URL chưa được cấu hình cho OAuth Meta.",
        )
    return f"{public_base_url}/api/oauth/meta/callback"


def _frontend_redirect(status: str, detail: str = "") -> RedirectResponse:
    params = {"meta": status}
    if detail:
        params["message"] = detail[:300]
    url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=303)


def _require_oauth_settings() -> tuple[str, str, str]:
    app_id = settings.META_APP_ID.strip()
    app_secret = settings.META_APP_SECRET.strip()
    redirect_uri = _redirect_uri()
    if not app_id or not app_secret:
        raise HTTPException(
            status_code=500,
            detail="Cần cấu hình META_APP_ID và META_APP_SECRET trong backend/.env.",
        )
    return app_id, app_secret, redirect_uri


def _graph_url(path: str) -> str:
    version = settings.META_GRAPH_VERSION.strip() or "v26.0"
    return f"https://graph.facebook.com/{version}/{path.lstrip('/')}"


async def _graph_get(
    client: httpx.AsyncClient,
    path: str,
    access_token: str,
    **params: str,
) -> dict:
    response = await client.get(
        _graph_url(path),
        params={"access_token": access_token, **params},
        timeout=30,
    )
    try:
        data = response.json()
    except ValueError:
        data = {"raw": response.text}
    if response.status_code >= 400:
        message = data.get("error", {}).get("message", "Meta API request failed")
        raise RuntimeError(message)
    return data


@router.get("/meta/status")
async def meta_oauth_status() -> dict:
    config = get_meta_config()
    # Do not treat the legacy single-shop values from .env as an OAuth
    # connection. OAuth is complete only after the callback persists the
    # Meta user and connection timestamp in app_settings.
    oauth_connected = bool(
        config["facebook_page_access_token"]
        and config["meta_user_id"]
        and config["connected_at"]
    )
    return {
        "connected": oauth_connected,
        "facebook_page_id": config["facebook_page_id"],
        "facebook_page_name": config["facebook_page_name"],
        "instagram_account_id": config["instagram_account_id"],
        "instagram_account_name": config["instagram_account_name"],
        "subscription_status": config["subscription_status"],
        "connected_at": config["connected_at"],
    }


@router.get("/meta/start")
async def start_meta_oauth() -> RedirectResponse:
    app_id, _, redirect_uri = _require_oauth_settings()
    state = secrets.token_urlsafe(32)
    save_settings(
        {
            META_KEYS["oauth_state"]: state,
            META_KEYS["oauth_state_created_at"]: str(time.time()),
        }
    )

    scope = (
        "pages_show_list,pages_read_engagement,pages_manage_metadata,"
        "pages_messaging,instagram_basic,instagram_manage_messages"
    )
    query = urlencode(
        {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": scope,
            "response_type": "code",
        }
    )
    return RedirectResponse(
        url=f"https://www.facebook.com/{settings.META_GRAPH_VERSION}/dialog/oauth?{query}",
        status_code=307,
    )


@router.get("/meta/callback")
async def meta_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
) -> RedirectResponse:
    if error:
        return _frontend_redirect("error", error_description or error)

    expected_state = get_setting_value(META_KEYS["oauth_state"])
    created_at = get_setting_value(META_KEYS["oauth_state_created_at"])
    try:
        state_is_fresh = time.time() - float(created_at) < 600
    except (TypeError, ValueError):
        state_is_fresh = False

    if not code or not state or state != expected_state or not state_is_fresh:
        return _frontend_redirect("error", "OAuth state không hợp lệ hoặc đã hết hạn.")

    try:
        app_id, app_secret, redirect_uri = _require_oauth_settings()
        async with httpx.AsyncClient() as client:
            token_response = await client.get(
                _graph_url("oauth/access_token"),
                params={
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
                timeout=30,
            )
            token_data = token_response.json()
            if token_response.status_code >= 400 or not token_data.get("access_token"):
                raise RuntimeError(
                    token_data.get("error", {}).get(
                        "message", "Không đổi được OAuth code thành access token."
                    )
                )

            user_token = token_data["access_token"]
            user = await _graph_get(
                client,
                "me",
                user_token,
                fields="id,name",
            )
            pages = await _graph_get(
                client,
                "me/accounts",
                user_token,
                fields="id,name,access_token,instagram_business_account",
            )

            available_pages = pages.get("data", [])
            if not available_pages:
                raise RuntimeError("Tài khoản Meta không có Facebook Page nào để kết nối.")

            preferred_page_id = (
                settings.META_DEFAULT_PAGE_ID.strip()
                or settings.FACEBOOK_PAGE_ID.strip()
            )
            page = next(
                (
                    item
                    for item in available_pages
                    if preferred_page_id and item.get("id") == preferred_page_id
                ),
                available_pages[0],
            )
            page_token = page.get("access_token")
            if not page.get("id") or not page_token:
                raise RuntimeError(
                    "Meta không trả về Page Access Token. Hãy cấp pages_manage_metadata."
                )

            instagram = page.get("instagram_business_account") or {}
            subscription_status = "not_attempted"
            subscription_response = await client.post(
                _graph_url(f"{page['id']}/subscribed_apps"),
                params={
                    "access_token": page_token,
                    "subscribed_fields": "messages",
                },
                timeout=30,
            )
            if subscription_response.status_code < 400:
                subscription_status = "subscribed_messages"
            else:
                subscription_status = "subscription_failed"

            save_meta_config(
                {
                    "facebook_page_id": str(page["id"]),
                    "facebook_page_name": str(page.get("name") or ""),
                    "facebook_page_access_token": str(page_token),
                    "instagram_account_id": str(instagram.get("id") or ""),
                    "meta_user_id": str(user.get("id") or ""),
                    "meta_user_name": str(user.get("name") or ""),
                    "connected_at": datetime.now(timezone.utc).isoformat(),
                    "subscription_status": subscription_status,
                    "oauth_state": "",
                    "oauth_state_created_at": "",
                }
            )

            return _frontend_redirect("connected", subscription_status)
    except Exception as exc:
        return _frontend_redirect("error", str(exc))


@router.delete("/meta/disconnect")
async def disconnect_meta() -> dict:
    clear_meta_config()
    return {"connected": False}
