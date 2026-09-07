import logging
import json

from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import settings
from app.services.message_service import normalize_message
from app.tenancy.webhook import verify_tiktok_webhook_signature

router = APIRouter(tags=["TikTok"])
logger = logging.getLogger(__name__)


@router.post("")
async def receive_tiktok_webhook(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    raw_body = await request.body()

    if not settings.TIKTOK_APP_KEY or not settings.TIKTOK_APP_SECRET:
        raise HTTPException(status_code=503, detail="TikTok webhook is not configured")
    if not verify_tiktok_webhook_signature(
        raw_body,
        authorization=authorization,
        app_key=settings.TIKTOK_APP_KEY,
        app_secret=settings.TIKTOK_APP_SECRET,
    ):
        raise HTTPException(status_code=401, detail="Invalid TikTok webhook signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid TikTok webhook JSON") from exc

    normalized = normalize_message(
        channel="tiktok",
        payload=payload,
    )

    # ``normalize_message`` returns a dict, and payloads must never be
    # printed because they may include customer content or provider secrets.
    logger.info(
        "TikTok webhook received: is_message=%s",
        bool(normalized.get("external_message_id")),
    )

    return {"status": "received"}
