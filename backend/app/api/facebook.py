from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.dependencies import get_db
from app.services.message_service import (
    normalize_message,
    process_and_save_message,
)
from app.services.realtime import manager
from app.tenancy.webhook import resolve_active_channel, verify_meta_signature
from app.integrations import get_channel_adapter
from app.services.channel_event_service import ingest_normalized_events

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
    request: Request,
    db: Session = Depends(get_db),
    x_hub_signature_256: str | None = Header(default=None),
):
    """
    Nhận webhook message từ Facebook,
    chuẩn hóa dữ liệu,
    tạo customer/conversation nếu cần,
    rồi lưu message vào PostgreSQL.
    """

    print("FACEBOOK RAW:", payload)

    if settings.ENVIRONMENT == "production" and not settings.META_APP_SECRET:
        raise HTTPException(status_code=500, detail="META_APP_SECRET is required")
    if settings.META_APP_SECRET and not verify_meta_signature(
        await request.body(), x_hub_signature_256, settings.META_APP_SECRET
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    adapter_events = get_channel_adapter("facebook").parse_events(payload)
    accepted_events = ingest_normalized_events(db, adapter_events) if settings.ENVIRONMENT == "production" else []
    if settings.ENVIRONMENT == "production" and adapter_events and not accepted_events:
        return {"status": "duplicate_or_unknown_channel"}

    if accepted_events:
        processed = 0
        for event in accepted_events:
            for item in event.messages:
                message = {
                    "channel": event.provider.value,
                    "external_user_id": item.sender_external_id,
                    "external_message_id": item.external_message_id,
                    "content": item.text,
                    "media_type": item.message_type.value,
                    "media_url": item.attachments[0].url if item.attachments else None,
                    "attachments": [attachment.model_dump(mode="json") for attachment in item.attachments],
                    "raw_payload": event.raw_payload,
                    "external_account_id": event.external_account_id,
                    "business_id": event.business_id,
                    "channel_id": event.channel_id,
                }
                saved_message = process_and_save_message(db=db, message=message)
                if isinstance(saved_message, dict):
                    processed += 1
                    await manager.broadcast({"type": "message_created", "conversation_id": saved_message.get("conversation_id"), "message": saved_message})
        return {"status": "received", "processed": processed}

    normalized = normalize_message(
        channel="facebook",
        payload=payload,
    )
    channel_binding = resolve_active_channel(
        db, "facebook", normalized.get("external_account_id")
    )
    normalized["business_id"] = channel_binding.business_id if channel_binding else None
    normalized["channel_id"] = channel_binding.id if channel_binding else None
    if settings.ENVIRONMENT == "production" and normalized["business_id"] is None:
        raise HTTPException(status_code=404, detail="Unknown Facebook channel account")

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
