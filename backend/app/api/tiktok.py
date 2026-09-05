import logging

from fastapi import APIRouter, Request

from app.services.message_service import normalize_message

router = APIRouter(prefix="/webhooks/tiktok", tags=["TikTok"])
logger = logging.getLogger(__name__)


@router.post("")
async def receive_tiktok_webhook(request: Request):
    payload = await request.json()

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
