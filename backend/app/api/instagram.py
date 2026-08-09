import json
import sys

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import PlainTextResponse

from app.services.message_service import normalize_message
from app.core.config import settings

# Fix Unicode print trên Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _safe_print(label: str, data) -> None:
    """Print an toàn với mọi encoding."""
    try:
        print(label, json.dumps(data, ensure_ascii=False, default=str))
    except Exception:
        print(label, json.dumps(data, ensure_ascii=True, default=str))

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
        print("[OK] INSTAGRAM WEBHOOK VERIFIED")
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

    _safe_print("INSTAGRAM RAW:", payload)
    _safe_print("INSTAGRAM NORMALIZED:", normalized)

    return {"status": "received"}