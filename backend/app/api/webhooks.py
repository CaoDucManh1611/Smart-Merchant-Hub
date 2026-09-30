"""Shared per-shop webhook entrypoint for bot providers.

The public URL is ``/api/webhooks/{shop_slug}``.  Telegram and Zalo can share
that path because their signed headers identify the provider; the existing
provider-specific URLs remain registered for backwards compatibility.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from app.database.platform_session import get_platform_db
from sqlalchemy.orm import Session

from app.api.telegram import receive_telegram_webhook
from app.api.zalo import receive_zalo_webhook
from app.models.platform_control import PlatformBusiness
from app.tenancy.registry import resolve_webhook_route


router = APIRouter()


def _zalo_route_key(payload: dict, request: Request) -> str:
    # OA events use the signature + recipient/OA id route key.  Prefer that
    # shape when both headers are present so the generic dispatcher matches
    # the same key as the provider-specific Zalo handler.
    if request.headers.get("x-zevent-signature"):
        recipient = payload.get("recipient") if isinstance(payload, dict) else None
        recipient_id = recipient.get("id") if isinstance(recipient, dict) else None
        return str(payload.get("oa_id") or recipient_id or payload.get("app_id") or "").strip()
    if request.headers.get("x-bot-api-secret-token"):
        return request.headers["x-bot-api-secret-token"]
    recipient = payload.get("recipient") if isinstance(payload, dict) else None
    recipient_id = recipient.get("id") if isinstance(recipient, dict) else None
    return str(payload.get("oa_id") or recipient_id or payload.get("app_id") or "").strip()


@router.post("/webhooks/{shop_slug}")
async def receive_shop_webhook(
    shop_slug: str,
    payload: dict,
    request: Request,
    platform_db: Session = Depends(get_platform_db),
):
    """Dispatch one shop-scoped webhook to the correct provider adapter."""

    telegram_secret = request.headers.get("x-telegram-bot-api-secret-token")
    zalo_secret = request.headers.get("x-bot-api-secret-token")
    zalo_signature = request.headers.get("x-zevent-signature")
    if telegram_secret:
        provider = "telegram"
        route_key = telegram_secret
    elif zalo_secret or zalo_signature:
        provider = "zalo"
        route_key = _zalo_route_key(payload, request)
    else:
        raise HTTPException(status_code=401, detail="Invalid webhook provider signature")

    try:
        route = resolve_webhook_route(platform_db, provider, route_key)
    except RuntimeError:
        route = None
    if route is None:
        raise HTTPException(status_code=401, detail="Invalid webhook route")
    registered_business = platform_db.get(PlatformBusiness, route.business_id)
    if registered_business is None or registered_business.slug != str(shop_slug).strip().lower():
        raise HTTPException(status_code=404, detail="Webhook shop không tồn tại.")

    if provider == "telegram":
        return await receive_telegram_webhook(
            payload=payload,
            request=request,
            platform_db=platform_db,
            x_telegram_bot_api_secret_token=telegram_secret,
        )
    return await receive_zalo_webhook(
        request=request,
        payload=payload,
        platform_db=platform_db,
        x_bot_api_secret_token=zalo_secret,
        x_zevent_signature=zalo_signature,
    )
