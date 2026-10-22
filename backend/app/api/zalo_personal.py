"""Inbound bridge for the Zalo personal-account helper.

The helper in ``zalo_bot.py`` keeps the Zalo Web cookies/IMEI on the shop's
machine and forwards only normalized messages here.  This endpoint never
receives or stores those cookies; it persists the message in the selected
shop's tenant schema and lets the normal CRM auto-reply worker continue.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings
from app.database.tenant_session import tenant_session
from app.models.channel import Channel
from app.services.message_service import process_and_save_message
from app.tenancy.schema import schema_name_for


router = APIRouter(prefix="/channels/zalo", tags=["Zalo personal bridge"])


class ZaloPersonalIncoming(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    author_id: str = Field(..., alias="authorId", min_length=1, max_length=255)
    thread_id: str = Field(..., alias="threadId", min_length=1, max_length=255)
    message: str = Field(default="", max_length=10000)
    media_type: str | None = Field(default=None, alias="mediaType", max_length=30)
    media_url: str | None = Field(default=None, alias="mediaUrl", max_length=2000)
    media_id: str | None = Field(default=None, alias="mediaId", max_length=500)
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    display_name: str | None = Field(default=None, alias="displayName", max_length=255)
    business_id: int | None = Field(default=None, alias="businessId", gt=0)
    message_id: str | None = Field(default=None, alias="messageId", max_length=255)
    channel_id: int | None = Field(default=None, alias="channelId", gt=0)

    @model_validator(mode="after")
    def require_message_or_image(self):
        media_type = (self.media_type or "").strip().lower()
        image_attachment = next((
            item for item in self.attachments
            if str(item.get("media_type") or item.get("type") or "").lower() == "image"
        ), None)
        image_url = self.media_url or (
            image_attachment.get("url") or image_attachment.get("source_url") or image_attachment.get("media_url")
            if image_attachment else None
        )
        if media_type == "image" and not image_url:
            raise ValueError("Ảnh cần có đường dẫn công khai để hệ thống phân tích.")
        if not self.message.strip() and not image_url:
            raise ValueError("Tin nhắn cần có nội dung hoặc ảnh đính kèm.")
        if image_url:
            try:
                parsed = urlsplit(str(image_url).strip())
                if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError
                parsed.port
            except ValueError as exc:
                raise ValueError("Link ảnh phải là URL HTTP(S) hợp lệ.") from exc
        return self


@router.post("/incoming")
def receive_personal_zalo_message(
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

        attachments = list(payload.attachments)
        has_image_attachment = any(
            str(item.get("media_type") or item.get("type") or "").lower() == "image"
            for item in attachments
        )
        media_type = (
            payload.media_type or ("image" if payload.media_url or has_image_attachment else "text")
        ).strip().lower()
        if payload.media_url and media_type == "text":
            media_type = "image"
        if media_type == "image" and not attachments:
            attachments = [{
                "media_type": "image",
                "url": payload.media_url,
                "external_attachment_id": payload.media_id,
            }]
        content = payload.message.strip() or f"[{media_type}]"
        fallback_id = hashlib.sha256(
            json.dumps(
                [
                    payload.thread_id,
                    payload.author_id,
                    payload.message,
                    payload.media_type,
                    payload.media_id,
                    payload.media_url,
                    attachments,
                ],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        saved = process_and_save_message(
            db=db,
            message={
                "channel": "zalo",
                "external_account_id": channel.external_account_id,
                "external_user_id": payload.author_id,
                "external_message_id": payload.message_id or f"personal:{fallback_id}",
                "content": content,
                "media_type": media_type if media_type != "text" else None,
                "media_url": payload.media_url,
                "attachments": attachments,
                "name": payload.display_name,
                "display_name": payload.display_name,
                "raw_payload": payload.model_dump(by_alias=True),
                "business_id": business_id,
                "channel_id": channel.id,
            },
        )
        if not isinstance(saved, dict):
            raise HTTPException(status_code=422, detail="Tin nhắn Zalo chưa được ghi nhận.")
        return {
            "status": "received",
            "conversation_id": saved.get("conversation_id"),
            "message_id": saved.get("message_id"),
            # The existing CRM worker sends the reply asynchronously. The
            # bridge treats a null response as an accepted, queued message.
            "response": None,
        }
