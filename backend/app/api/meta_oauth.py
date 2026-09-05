"""Meta OAuth connection flow for Facebook Pages and linked Instagram."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from app.db.database import SessionLocal

from app.core.config import settings
from app.models.channel import Channel
from app.auth.dependencies import require_admin_access
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.tenancy.oauth import consume_oauth_state, issue_oauth_state, register_oauth_state
from app.services.channel_service import upsert_channel_connection


router = APIRouter()
logger = logging.getLogger(__name__)


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
async def meta_oauth_status(
    tenant: TenantContext = Depends(get_tenant_context),
) -> dict:
    # Credential state is tenant-owned in ``channels``.  app_settings only
    # retains non-secret display metadata during the transition from the old
    # single-shop integration.
    with SessionLocal() as db:
        facebook = db.query(Channel).filter(
            Channel.business_id == tenant.business_id,
            Channel.channel_type == "facebook",
            Channel.status == "active",
            Channel.access_token_encrypted.is_not(None),
        ).first()
        instagram = db.query(Channel).filter(
            Channel.business_id == tenant.business_id,
            Channel.channel_type == "instagram",
            Channel.status == "active",
        ).first()

    channel_config = facebook.config or {} if facebook else {}
    connected_at = (
        facebook.connected_at or facebook.created_at
        if facebook else None
    )
    return {
        "connected": facebook is not None,
        "facebook_page_id": facebook.external_account_id if facebook else "",
        "facebook_page_name": facebook.name if facebook else "",
        "instagram_account_id": instagram.external_account_id if instagram else "",
        "instagram_account_name": instagram.name if instagram else "",
        "subscription_status": channel_config.get("subscription_status", "not_attempted"),
        "connected_at": connected_at.isoformat() if connected_at else "",
    }


@router.get("/meta/start", dependencies=[Depends(require_admin_access)])
async def start_meta_oauth(
    tenant: TenantContext = Depends(get_tenant_context),
    return_url: bool = Query(default=False),
) -> RedirectResponse | dict:
    app_id, _, redirect_uri = _require_oauth_settings()
    if not settings.META_APP_SECRET:
        raise HTTPException(status_code=500, detail="META_APP_SECRET is required for signed OAuth state")
    state = issue_oauth_state(tenant.business_id, settings.META_APP_SECRET)
    with SessionLocal() as db:
        register_oauth_state(db, state, settings.META_APP_SECRET)
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
    authorization_url = (
        f"https://www.facebook.com/{settings.META_GRAPH_VERSION}/dialog/oauth?{query}"
    )
    # A browser navigation cannot attach the CRM bearer token.  The SPA asks
    # for this JSON form through its authenticated API helper, then navigates
    # to Meta only after a tenant-scoped state has been issued.
    if return_url:
        return {"authorization_url": authorization_url}
    return RedirectResponse(url=authorization_url, status_code=307)


@router.get("/meta/callback")
async def meta_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
) -> RedirectResponse:
    if error:
        return _frontend_redirect("error", error_description or error)

    try:
        with SessionLocal() as db:
            state_payload = consume_oauth_state(db, state or "", settings.META_APP_SECRET)
    except PermissionError:
        return _frontend_redirect("error", "OAuth state không hợp lệ hoặc đã hết hạn.")
    if not code:
        return _frontend_redirect("error", "OAuth code không hợp lệ.")

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
            if not settings.CHANNEL_ENCRYPTION_KEY:
                raise RuntimeError("CHANNEL_ENCRYPTION_KEY is required for channel credentials")
            with SessionLocal() as db:
                upsert_channel_connection(
                    db,
                    business_id=int(state_payload["business_id"]),
                    channel_type="facebook",
                    external_account_id=str(page["id"]),
                    name=str(page.get("name") or page["id"]),
                    access_token=str(page_token),
                    config={"meta_user_id": str(user.get("id") or "")},
                )
                if instagram.get("id"):
                    upsert_channel_connection(
                        db,
                        business_id=int(state_payload["business_id"]),
                        channel_type="instagram",
                        external_account_id=str(instagram["id"]),
                        name=str(instagram.get("username") or instagram["id"]),
                        access_token=str(page_token),
                        config={"facebook_page_id": str(page["id"])},
                    )
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

            with SessionLocal() as db:
                facebook_channel = db.query(Channel).filter(
                    Channel.business_id == int(state_payload["business_id"]),
                    Channel.channel_type == "facebook",
                    Channel.external_account_id == str(page["id"]),
                ).first()
                if facebook_channel is not None:
                    facebook_channel.config = {
                        **(facebook_channel.config or {}),
                        "meta_user_id": str(user.get("id") or ""),
                        "subscription_status": subscription_status,
                    }
                    db.commit()

            return _frontend_redirect("connected", subscription_status)
    except Exception:
        # Provider errors can contain request or account data.  Keep detailed
        # diagnostics only in the redacted server log and never reflect them
        # into a browser URL.
        logger.exception("Meta OAuth callback failed")
        return _frontend_redirect("error", "Không thể hoàn tất kết nối Meta. Hãy thử lại.")


@router.delete("/meta/disconnect", dependencies=[Depends(require_admin_access)])
async def disconnect_meta(
    tenant: TenantContext = Depends(get_tenant_context),
) -> dict:
    """Revoke only this tenant's stored Meta channel credentials."""
    with SessionLocal() as db:
        channels = db.query(Channel).filter(
            Channel.business_id == tenant.business_id,
            Channel.channel_type.in_(("facebook", "instagram")),
        ).all()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for channel in channels:
            channel.status = "inactive"
            channel.access_token = None
            channel.access_token_encrypted = None
            channel.disconnected_at = now
        db.commit()
    return {"connected": False}
