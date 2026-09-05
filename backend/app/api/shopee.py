import logging

from fastapi import APIRouter, Request

from app.services.message_service import normalize_message

router = APIRouter(prefix="/webhooks/shopee", tags=["Shopee"])
logger = logging.getLogger(__name__)


@router.post("")
async def receive_shopee_webhook(request: Request):
    payload = await request.json()

    normalized = normalize_message(
        channel="shopee",
        payload=payload,
    )

    # ``normalize_message`` returns a dict, and payloads must never be
    # printed because they may include customer content or provider secrets.
    logger.info(
        "Shopee webhook received: is_message=%s",
        bool(normalized.get("external_message_id")),
    )

    return {"status": "received"}
