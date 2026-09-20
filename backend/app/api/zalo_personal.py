"""Inbound bridge for the Zalo personal-account helper.

The helper in ``zalo_bot.py`` keeps the Zalo Web cookies/IMEI on the shop's
machine and forwards only normalized messages here.  This endpoint never
receives or stores those cookies; it persists the message in the selected
shop's tenant schema and lets the normal CRM auto-reply worker continue.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.database.tenant_session import tenant_session
from app.models.channel import Channel
from app.services.message_service import process_and_save_message
from app.services.realtime import manager
from app.tenancy.schema import schema_name_for


router = APIRouter(prefix="/channels/zalo", tags=["Zalo personal bridge"])


class ZaloPersonalIncoming(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    author_id: str = Field(..., alias="authorId", min_length=1, max_length=255)
    thread_id: str = Field(..., alias="threadId", min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=10000)
    display_name: str | None = Field(default=None, alias="displayName", max_length=255)
    business_id: int | None = Field(default=None, alias="businessId", gt=0)
    message_id: str | None = Field(default=None, alias="messageId", max_length=255)
    channel_id: int | None = Field(default=None, alias="channelId", gt=0)


@router.post("/incoming")
async def receive_personal_zalo_message(
    payload: ZaloPersonalIncoming,
    x_zalo_bridge_key: str | None = Header(default=None, alias="X-Zalo-Bridge-Key"),
    x_zalo_business_id: str | None = Header(default=None, alias="X-Zalo-Business-Id"),
):
    configured_key = str(settings.ZALO_PERSONAL_BRIDGE_KEY or "").strip()
    supplied_key = str(x_zalo_bridge_key or "").strip()
    if configured_key:
        if supplied_key != configured_key:
            raise HTTPException(status_code=401, detail="Mã kết nối Zalo bridge không hợp lệ.")
    elif settings.ENVIRONMENT.strip().lower() == "production":
        raise HTTPException(status_code=503, detail="Chưa cấu hình mã kết nối Zalo bridge.")

    business_id = payload.business_id
    if business_id is None and x_zalo_business_id:
        try:
            business_id = int(x_zalo_business_id)
        except ValueError:
            business_id = None
    if business_id is None and settings.ZALO_PERSONAL_BUSINESS_ID > 0:
        business_id = settings.ZALO_PERSONAL_BUSINESS_ID
    if business_id is None or business_id <= 0:
        raise HTTPException(status_code=422, detail="Thiếu mã shop cho kết nối Zalo cá nhân.")
    business_id = int(business_id)
    with tenant_session(schema_name_for(business_id)) as db:
        channel = None
        if payload.channel_id is not None:
            candidate = db.get(Channel, payload.channel_id)
            if candidate is not None and candidate.business_id == business_id and candidate.channel_type == "zalo":
                channel = candidate
        if channel is None:
            channel = (
                db.query(Channel)
                .filter(Channel.business_id == business_id, Channel.channel_type == "zalo", Channel.status == "active")
                .order_by(Channel.id.desc())
                .first()
            )
        if channel is None:
            raise HTTPException(status_code=404, detail="Shop chưa kết nối Zalo cá nhân.")

        saved = process_and_save_message(
            db=db,
            message={
                "channel": "zalo",
                "external_account_id": channel.external_account_id,
                "external_user_id": payload.author_id,
                "external_message_id": payload.message_id or f"personal:{payload.thread_id}:{payload.author_id}:{payload.message[:80]}",
                "content": payload.message,
                "name": payload.display_name,
                "display_name": payload.display_name,
                "raw_payload": payload.model_dump(by_alias=True),
                "business_id": business_id,
                "channel_id": channel.id,
            },
        )
        if not isinstance(saved, dict):
            raise HTTPException(status_code=422, detail="Tin nhắn Zalo chưa được ghi nhận.")
        if saved.get("_created", True):
            await manager.broadcast(
                {
                    "type": "message_created",
                    "conversation_id": saved.get("conversation_id"),
                    "message": {key: value for key, value in saved.items() if key != "_created"},
                },
                business_id=business_id,
            )
        return {
            "status": "received",
            "conversation_id": saved.get("conversation_id"),
            "message_id": saved.get("message_id"),
            # The existing CRM worker sends the reply asynchronously. The
            # bridge treats a null response as an accepted, queued message.
            "response": None,
        }
