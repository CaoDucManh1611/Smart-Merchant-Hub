from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.services.message_service import normalize_message

router = APIRouter(
    prefix="/webhooks/facebook",
    tags=["Facebook"],
)


@router.get("", response_class=PlainTextResponse)
async def verify_facebook_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    if (
        hub_mode == "subscribe"
        and hub_verify_token == settings.FACEBOOK_VERIFY_TOKEN
    ):
        return hub_challenge

    raise HTTPException(
        status_code=403,
        detail="Invalid verify token",
    )


@router.post("")
async def receive_facebook_webhook(payload: dict):
    normalized = normalize_message(
        channel="facebook",
        payload=payload,
    )

    print("FACEBOOK RAW:", payload)
    print("FACEBOOK NORMALIZED:", normalized)

    return {"status": "received"}