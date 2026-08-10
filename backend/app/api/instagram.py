from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.dependencies import get_db
from app.db.message_repository import save_message
from app.services.message_service import normalize_message

router = APIRouter()


@router.get("")
async def verify_instagram_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
):
    """
    Meta dùng endpoint GET này để verify webhook Instagram.
    """

    if (
        hub_mode == "subscribe"
        and hub_verify_token == settings.FACEBOOK_VERIFY_TOKEN
    ):
        print("✅ INSTAGRAM WEBHOOK VERIFIED")

        return PlainTextResponse(
            content=hub_challenge,
            status_code=200,
        )

    raise HTTPException(
        status_code=403,
        detail="Invalid Instagram verify token",
    )


@router.post("")
async def receive_instagram_webhook(
    payload: dict,
    db: Session = Depends(get_db),
):
    """
    Nhận webhook Instagram,
    normalize message,
    rồi lưu vào PostgreSQL.
    """

    print("INSTAGRAM RAW:", payload)

    normalized = normalize_message(
        channel="instagram",
        payload=payload,
    )

    print("INSTAGRAM NORMALIZED:", normalized)

    # Chỉ lưu khi thật sự có message
    if normalized.get("external_message_id"):
        save_message(
            db=db,
            message=normalized,
        )

        print("✅ INSTAGRAM MESSAGE SAVED TO POSTGRESQL")

    else:
        print("⚠️ INSTAGRAM EVENT IGNORED - NO MESSAGE ID")

    return {
        "status": "received"
    }