"""Instagram messaging webhook routed through the platform route registry."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.platform_session import get_platform_db
from app.api.facebook import _receive_meta_webhook


router = APIRouter()


@router.get("")
async def verify_instagram_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.FACEBOOK_VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Invalid Instagram verify token")


@router.post("")
async def receive_instagram_webhook(
    payload: dict,
    request: Request,
    platform_db: Session = Depends(get_platform_db),
    x_hub_signature_256: str | None = Header(default=None),
):
    return await _receive_meta_webhook(
        "instagram", payload, request, platform_db, x_hub_signature_256
    )
