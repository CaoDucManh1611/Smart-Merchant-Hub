from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import PlainTextResponse

from app.services.message_service import normalize_message
from app.core.config import settings

router = APIRouter(prefix="/webhooks/instagram", tags=["Instagram"])


@router.get("")
async def verify_instagram_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    if (
        hub_mode == "subscribe"
        and hub_verify_token == settings.FACEBOOK_VERIFY_TOKEN
    ):
        print("✅ INSTAGRAM WEBHOOK VERIFIED")
        return PlainTextResponse(content=hub_challenge)

    raise HTTPException(
        status_code=403,
        detail="Invalid verify token",
    )


@router.post("")
async def receive_instagram_webhook(request: Request):
    payload = await request.json()

    normalized = normalize_message(
        channel="instagram",
        payload=payload,
    )

    print("INSTAGRAM RAW:", payload)
    print("INSTAGRAM NORMALIZED:", normalized)

    return {"status": "received"}