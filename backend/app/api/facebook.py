from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.dependencies import get_db
from app.services.message_service import (
    normalize_message,
    process_and_save_message,
)
from app.services.realtime import manager

router = APIRouter()


@router.get("")
async def verify_facebook_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
):
    """
    Meta gọi endpoint này để xác minh webhook Facebook.
    """

    if (
        hub_mode == "subscribe"
        and hub_verify_token == settings.FACEBOOK_VERIFY_TOKEN
    ):
        print("✅ FACEBOOK WEBHOOK VERIFIED")

        return PlainTextResponse(
            content=hub_challenge,
            status_code=200,
        )

    raise HTTPException(
        status_code=403,
        detail="Invalid Facebook verify token",
    )


@router.post("")
async def receive_facebook_webhook(
    payload: dict,
    db: Session = Depends(get_db),
):
    """
    Nhận webhook message từ Facebook,
    chuẩn hóa dữ liệu,
    tạo customer/conversation nếu cần,
    rồi lưu message vào PostgreSQL.
    """

    print("FACEBOOK RAW:", payload)

    normalized = normalize_message(
        channel="facebook",
        payload=payload,
    )

    print("FACEBOOK NORMALIZED:", normalized)

    # Chỉ xử lý khi đây thực sự là một message
    if normalized.get("external_message_id"):

        saved_message = process_and_save_message(
            db=db,
            message=normalized,
        )

        if isinstance(
            saved_message,
            dict,
        ):
            await manager.broadcast(
                {
                    "type":
                        "message_created",
                    "conversation_id":
                        saved_message.get(
                            "conversation_id"
                        ),
                    "message":
                        saved_message,
                }
            )

        print(
            "✅ FACEBOOK MESSAGE PROCESSED "
            "AND SAVED TO POSTGRESQL"
        )

    else:
        print(
            "⚠️ FACEBOOK EVENT IGNORED "
            "- NO MESSAGE ID"
        )

    return {
        "status": "received",
    }
