"""Pairing and inbound messages for local TikTok/Shopee connectors."""

from __future__ import annotations

import hashlib
import hmac
from io import BytesIO
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_access
from app.core.config import settings
from app.database.platform_session import get_platform_db
from app.database.tenant_session import tenant_session
from app.models.business import User
from app.models.channel import Channel
from app.models.customer_identity import CustomerIdentity
from app.models.platform_control import PlatformBusiness, TenantRegistry
from app.services.audit_service import record_audit
from app.services.channel_credentials import decrypt_token, encrypt_token
from app.services.customer_profile import normalize_avatar_url
from app.services.message_service import process_and_save_message
from app.services.realtime import manager
from app.services.quota_service import QuotaExceededError, reserve_quota
from app.tenancy.schema import schema_name_for, validate_schema_name

router = APIRouter(tags=["Local channel connectors"])
_SUPPORTED = {"tiktok", "shopee"}
_CODE_RE = re.compile(r"^(PAIR|CONN)\.(tiktok|shopee)\.(\d+)\.(\d+)\.([A-Za-z0-9_-]{12,})$")


class PairConnectorRequest(BaseModel):
    pairing_code: str = Field(min_length=24, max_length=200)


class ConnectorHeartbeatRequest(BaseModel):
    state: str = Field(default="online", pattern="^(online|error)$")
    error_code: str | None = Field(default=None, max_length=80, pattern="^[a-zA-Z0-9_.-]+$")
    retry_ack_id: str | None = Field(default=None, max_length=80, pattern="^[A-Za-z0-9_-]+$")


def _code_parts(value: str, kind: str, channel_type: str | None = None) -> tuple[str, int, int, str]:
    match = _CODE_RE.fullmatch(str(value or "").strip())
    if not match or match.group(1) != kind or (channel_type and match.group(2) != channel_type):
        raise HTTPException(status_code=401, detail="Mã ghép nối không hợp lệ.")
    try:
        business_id, channel_id = int(match.group(3)), int(match.group(4))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Mã ghép nối không hợp lệ.") from exc
    return match.group(2), business_id, channel_id, match.group(5)


def _tenant_schema(platform_db: Session, business_id: int) -> str:
    business = platform_db.scalar(
        select(PlatformBusiness).where(
            PlatformBusiness.id == business_id,
            PlatformBusiness.status == "active",
        )
    )
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại hoặc đã ngừng hoạt động.")
    registry = platform_db.scalar(
        select(TenantRegistry).where(TenantRegistry.business_id == business_id)
    )
    if registry is not None and registry.state not in {"active", "ready"}:
        raise HTTPException(status_code=423, detail="Không gian shop chưa sẵn sàng.")
    return validate_schema_name(
        str(registry.schema_name) if registry is not None else schema_name_for(business_id)
    )


@router.post("/channels/pair")
def pair_local_connector(
    payload: PairConnectorRequest,
    response: Response,
    platform_db: Session = Depends(get_platform_db),
):
    """Exchange a one-time pairing code for the connector's shop-scoped token."""

    response.headers["Cache-Control"] = "no-store"
    channel_type, business_id, channel_id, _nonce = _code_parts(payload.pairing_code, "PAIR")
    schema = _tenant_schema(platform_db, business_id)
    supplied_hash = hashlib.sha256(payload.pairing_code.strip().encode("utf-8")).hexdigest()

    with tenant_session(schema) as tenant_db:
        channel = tenant_db.scalar(
            select(Channel)
            .where(
                Channel.id == channel_id,
                Channel.business_id == business_id,
                Channel.channel_type == channel_type,
                Channel.status.in_(("active", "pending_pairing")),
            )
            .with_for_update()
        )
        config = channel.config if channel and isinstance(channel.config, dict) else {}
        expected_hash = str(config.get("pairing_code_hash") or "")
        expires_at = int(config.get("pairing_code_expires_at") or 0)
        if not channel or not expected_hash or not hmac.compare_digest(expected_hash, supplied_hash):
            raise HTTPException(status_code=401, detail="Pairing code đã dùng hoặc không đúng.")
        if expires_at <= time.time():
            raise HTTPException(status_code=410, detail="Pairing code đã hết hạn. Hãy tạo mã mới trong Liên kết mạng xã hội.")
        try:
            connector_token = decrypt_token(
                str(config.get("pending_connector_token_encrypted") or ""),
                settings.CHANNEL_ENCRYPTION_KEY,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Không thể đọc cấu hình connector của shop.") from exc
        _code_parts(connector_token, "CONN", channel_type)
        channel.access_token_encrypted = encrypt_token(connector_token, settings.CHANNEL_ENCRYPTION_KEY)
        channel.access_token = None
        if channel.status == "pending_pairing":
            try:
                reserve_quota(platform_db, business_id, "connected_channels")
            except QuotaExceededError as exc:
                raise HTTPException(status_code=429, detail=exc.detail) from exc
            channel.status = "active"
            channel.connected_at = datetime.now(timezone.utc).replace(tzinfo=None)
        config = dict(config)
        config.pop("pairing_code_hash", None)
        config.pop("pairing_code_expires_at", None)
        config.pop("pending_connector_token_encrypted", None)
        config.pop("webhook_secret", None)
        config.pop("webhook_secret_encrypted", None)
        config.pop("bridge_control_url", None)
        config["connector_paired_at"] = int(time.time())
        channel.config = config
        tenant_db.flush()

    platform_db.commit()

    return {
        "channel_type": channel_type,
        "connector_token": connector_token,
        "incoming_endpoint": f"/api/channels/{channel_type}/incoming",
    }


def _connector_channel(
    channel_type: str,
    authorization: str | None,
    platform_db: Session,
) -> tuple[int, int]:
    scheme, _, token = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Thiếu connector token.")
    token = token.strip()
    parsed_type, business_id, channel_id, _nonce = _code_parts(token, "CONN", channel_type)
    schema = _tenant_schema(platform_db, business_id)

    with tenant_session(schema) as tenant_db:
        channel = tenant_db.scalar(
            select(Channel).where(
                Channel.id == channel_id,
                Channel.business_id == business_id,
                Channel.channel_type == parsed_type,
                Channel.status == "active",
            )
        )
        if channel is None:
            raise HTTPException(status_code=401, detail="Connector đã bị ngắt hoặc không còn hợp lệ.")
        try:
            expected = decrypt_token(
                str(channel.access_token_encrypted or ""),
                settings.CHANNEL_ENCRYPTION_KEY,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Không thể xác thực connector của shop.") from exc
        if not hmac.compare_digest(expected, token):
            raise HTTPException(status_code=401, detail="Connector token không hợp lệ.")
    return business_id, channel_id


@router.post("/channels/{channel_type}/heartbeat")
def report_connector_heartbeat(
    channel_type: str,
    payload: ConnectorHeartbeatRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    """Record a minimal, authenticated liveness/error signal; never accept raw logs."""
    if channel_type not in _SUPPORTED:
        raise HTTPException(status_code=404, detail="Kênh connector không được hỗ trợ.")
    business_id, channel_id = _connector_channel(channel_type, authorization, platform_db)
    schema = _tenant_schema(platform_db, business_id)
    with tenant_session(schema) as tenant_db:
        channel = tenant_db.scalar(select(Channel).where(
            Channel.id == channel_id,
            Channel.business_id == business_id,
            Channel.channel_type == channel_type,
            Channel.status == "active",
        ))
        if channel is None:
            raise HTTPException(status_code=401, detail="Connector đã bị ngắt hoặc không còn hợp lệ.")
        config = dict(channel.config) if isinstance(channel.config, dict) else {}
        now = datetime.now(timezone.utc)
        config["connector_last_seen_at"] = now.isoformat()
        config["connector_last_error_code"] = payload.error_code if payload.state == "error" else None
        config["connector_status"] = payload.state
        pending_retry_id = str(config.get("connector_retry_id") or "")
        requested_at = config.get("connector_retry_requested_at")
        if pending_retry_id and requested_at:
            try:
                requested_time = datetime.fromisoformat(str(requested_at).replace("Z", "+00:00"))
                if (now - requested_time.astimezone(timezone.utc)).total_seconds() > 300:
                    config.pop("connector_retry_id", None)
                    config.pop("connector_retry_requested_at", None)
                    pending_retry_id = ""
            except (TypeError, ValueError):
                config.pop("connector_retry_id", None)
                config.pop("connector_retry_requested_at", None)
                pending_retry_id = ""
        retry_acknowledged = bool(pending_retry_id and payload.retry_ack_id == pending_retry_id)
        if retry_acknowledged:
            config.pop("connector_retry_id", None)
            config.pop("connector_retry_requested_at", None)
        channel.config = config
        tenant_db.commit()
    result = {"status": "recorded", "connector_status": payload.state}
    if retry_acknowledged:
        result["retry_acknowledged"] = True
    elif pending_retry_id:
        result["retry_id"] = pending_retry_id
    return result


async def receive_local_connector_message(
    channel_type: str,
    payload: dict,
    authorization: str | None,
    platform_db: Session,
):
    if channel_type not in _SUPPORTED:
        raise HTTPException(status_code=404, detail="Kênh connector không được hỗ trợ.")
    if len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")) > 262144:
        raise HTTPException(status_code=413, detail="Tin nhắn gửi lên vượt quá dung lượng cho phép.")

    business_id, channel_id = _connector_channel(channel_type, authorization, platform_db)
    # Seller Chat also emits shop/system cards. They are not customer text and
    # must not enter the conversation-turn queue or trigger an AI reply.
    message_type = str(payload.get("messageType") or payload.get("message_type") or "text").strip().lower()
    if message_type not in {"text", "image", "video", "audio", "file", "sticker"}:
        return {"status": "ignored", "processed": 0}
    sender_id = str(payload.get("authorId") or payload.get("sender_id") or payload.get("from_id") or "").strip()
    thread_id = str(payload.get("threadId") or payload.get("conversation_id") or payload.get("conv_id") or "").strip()
    content = str(payload.get("message") or payload.get("text") or "").strip()
    if not sender_id or not thread_id:
        raise HTTPException(status_code=422, detail="Tin nhắn thiếu mã khách hoặc cuộc hội thoại.")
    if not content and message_type not in {"image", "video", "audio", "file", "sticker"}:
        raise HTTPException(status_code=422, detail="Tin nhắn không có nội dung.")
    if not content:
        content = f"[{message_type}]"
    content = content[:10000]
    external_message_id = str(payload.get("messageId") or payload.get("message_id") or payload.get("id") or "").strip()
    if not external_message_id:
        seed = "|".join((channel_type, thread_id, sender_id, content, str(payload.get("createdAt") or "")))
        external_message_id = "local-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()
    external_message_id = external_message_id[:255]

    schema = _tenant_schema(platform_db, business_id)
    with tenant_session(schema) as tenant_db:
        channel = tenant_db.get(Channel, channel_id)
        if not channel or channel.business_id != business_id or channel.channel_type != channel_type or channel.status != "active":
            raise HTTPException(status_code=401, detail="Kênh đã bị ngắt hoặc không còn hợp lệ.")
        attachments = payload.get("attachments")
        if not isinstance(attachments, list):
            attachments = []
        saved = process_and_save_message(
            db=tenant_db,
            message={
                "channel": channel_type,
                "external_account_id": channel.external_account_id,
                "external_user_id": sender_id[:255],
                "external_message_id": external_message_id,
                "content": content,
                "name": str(payload.get("displayName") or payload.get("display_name") or "")[:255] or None,
                "display_name": str(payload.get("displayName") or payload.get("display_name") or "")[:255] or None,
                "username": str(payload.get("username") or "")[:255] or None,
                "avatar_url": str(payload.get("avatarUrl") or payload.get("avatar_url") or "")[:2000] or None,
                "media_type": message_type if message_type in {"image", "video", "audio", "file", "sticker"} else None,
                "media_url": str(payload.get("mediaUrl") or payload.get("media_url") or "")[:2000] or None,
                "attachments": attachments[:20],
                "raw_payload": {
                    "threadId": thread_id,
                    "message_type": message_type,
                    "created_at": str(payload.get("createdAt") or payload.get("created_at") or "")[:100],
                    "source": str(payload.get("source") or "local_connector")[:100],
                },
                "business_id": business_id,
                "channel_id": channel_id,
            },
        )
        if not isinstance(saved, dict):
            raise HTTPException(status_code=500, detail="Không thể lưu tin nhắn từ connector.")
        if saved.get("_created", True):
            await manager.broadcast(
                {
                    "type": "message_created",
                    "conversation_id": saved.get("conversation_id"),
                    "message": {key: value for key, value in saved.items() if key != "_created"},
                },
                business_id=business_id,
            )
        return {"status": "received", "processed": 1 if saved.get("_created", True) else 0}


def _history_datetime(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    text_value = str(value or "").strip()
    if not text_value:
        return None
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def _normalize_history_message(channel_type: str, item: object) -> dict | None:
    if not isinstance(item, dict):
        return None
    thread_id = str(item.get("threadId") or item.get("conversationId") or "").strip()[:255]
    customer_id = str(item.get("customerId") or item.get("externalUserId") or "").strip()[:255]
    message_id = str(item.get("messageId") or item.get("message_id") or "").strip()[:255]
    direction = str(item.get("direction") or "inbound").strip().lower()
    content = str(item.get("message") or item.get("text") or "").strip()[:10000]
    message_type = str(item.get("messageType") or item.get("message_type") or "text").strip().lower()
    if direction not in {"inbound", "outbound"}:
        return None
    if not thread_id or not customer_id or not message_id:
        return None
    if message_type not in {"text", "image", "video", "audio", "file", "sticker"}:
        return None
    if not content and message_type == "text":
        return None
    return {
        "thread_id": thread_id,
        "customer_id": customer_id,
        "message_id": message_id,
        "direction": direction,
        "content": content or f"[{message_type}]",
        "message_type": message_type,
        "display_name": str(item.get("displayName") or item.get("display_name") or "")[:255] or None,
        "username": str(item.get("username") or "")[:255] or None,
        "avatar_url": str(item.get("avatarUrl") or item.get("avatar_url") or "")[:2000] or None,
        "media_url": str(item.get("mediaUrl") or item.get("media_url") or "")[:2000] or None,
        "attachments": item.get("attachments") if isinstance(item.get("attachments"), list) else [],
        "created_at": _history_datetime(item.get("createdAt") or item.get("created_at") or item.get("timestamp")),
    }


def receive_local_connector_history(
    channel_type: str,
    payload: dict,
    authorization: str | None,
    platform_db: Session,
):
    """Safely import an idempotent batch of prior chat messages without automation."""
    if channel_type not in _SUPPORTED:
        raise HTTPException(status_code=404, detail="Kênh connector không được hỗ trợ.")
    if len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")) > 1_500_000:
        raise HTTPException(status_code=413, detail="Lô lịch sử vượt quá dung lượng cho phép.")
    items = payload.get("messages")
    if not isinstance(items, list) or not items or len(items) > 100:
        raise HTTPException(status_code=422, detail="Mỗi lô lịch sử phải có từ 1 đến 100 tin nhắn.")
    business_id, channel_id = _connector_channel(channel_type, authorization, platform_db)
    schema = _tenant_schema(platform_db, business_id)
    imported = duplicates = skipped = 0
    with tenant_session(schema) as tenant_db:
        channel = tenant_db.get(Channel, channel_id)
        if not channel or channel.business_id != business_id or channel.channel_type != channel_type or channel.status != "active":
            raise HTTPException(status_code=401, detail="Kênh đã bị ngắt hoặc không còn hợp lệ.")
        for item in items:
            normalized = _normalize_history_message(channel_type, item)
            if normalized is None:
                skipped += 1
                continue
            thread_id = normalized["thread_id"]
            message_type = normalized["message_type"]
            saved = process_and_save_message(
                db=tenant_db,
                history_import=True,
                message={
                    "channel": channel_type,
                    "external_account_id": channel.external_account_id,
                    # Outbound cards still belong to the buyer's conversation.
                    "external_user_id": normalized["customer_id"],
                    "external_message_id": normalized["message_id"],
                    "direction": normalized["direction"],
                    "content": normalized["content"],
                    "name": normalized["display_name"],
                    "display_name": normalized["display_name"],
                    "username": normalized["username"],
                    "avatar_url": normalized["avatar_url"],
                    "media_type": message_type if message_type in {"image", "video", "audio", "file", "sticker"} else None,
                    "media_url": normalized["media_url"],
                    "attachments": normalized["attachments"][:20],
                    "received_at": normalized["created_at"],
                    "raw_payload": {
                        "threadId": thread_id,
                        "history_import": True,
                        "message_type": message_type,
                        "created_at": normalized["created_at"].isoformat() if normalized["created_at"] else None,
                    },
                    "business_id": business_id,
                    "channel_id": channel_id,
                },
            )
            if not isinstance(saved, dict):
                raise HTTPException(status_code=500, detail="Không thể lưu tin nhắn lịch sử.")
            if saved.get("_created", True):
                imported += 1
            else:
                duplicates += 1
    return {"status": "received", "imported": imported, "duplicates": duplicates, "skipped": skipped}


@router.post("/channels/{channel_type}/history")
def receive_shopee_tiktok_history(
    channel_type: str,
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    return receive_local_connector_history(channel_type, payload, authorization, platform_db)


@router.post("/channels/shopee/incoming")
async def receive_shopee_connector_message(
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    return await receive_local_connector_message("shopee", payload, authorization, platform_db)


@router.post("/channels/shopee/profiles")
def sync_shopee_customer_avatars(
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    return _sync_local_connector_customer_avatars("shopee", payload, authorization, platform_db)


@router.post("/channels/tiktok/profiles")
def sync_tiktok_customer_avatars(
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    return _sync_local_connector_customer_avatars("tiktok", payload, authorization, platform_db)


def _sync_local_connector_customer_avatars(
    channel_type: str,
    payload: dict,
    authorization: str | None,
    platform_db: Session,
):
    """Fill missing avatars for known connector identities; never create customers."""
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or len(profiles) > 200:
        raise HTTPException(status_code=422, detail="Danh sách hồ sơ connector không hợp lệ.")
    avatars = {}
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        external_user_id = str(profile.get("externalUserId") or "").strip()[:255]
        avatar_url = normalize_avatar_url(profile.get("avatarUrl"))
        if external_user_id and avatar_url:
            avatars[external_user_id] = avatar_url
    if not avatars:
        return {"status": "unchanged", "updated": 0}

    business_id, channel_id = _connector_channel(channel_type, authorization, platform_db)
    schema = _tenant_schema(platform_db, business_id)
    updated = 0
    matched_external_user_ids: set[str] = set()
    with tenant_session(schema) as tenant_db:
        channel = tenant_db.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(status_code=401, detail="Shopee connector không còn hợp lệ.")
        identities = tenant_db.scalars(
            select(CustomerIdentity).where(
                CustomerIdentity.business_id == business_id,
                CustomerIdentity.channel == channel_type,
                CustomerIdentity.external_account_id == str(channel.external_account_id or ""),
                CustomerIdentity.external_user_id.in_(avatars),
            )
        ).all()
        for identity in identities:
            matched_external_user_ids.add(identity.external_user_id)
            customer = identity.customer
            avatar_url = avatars.get(identity.external_user_id)
            if customer.business_id != business_id or not avatar_url or customer.avatar_url:
                continue
            customer.avatar_url = avatar_url
            record_audit(
                tenant_db,
                business_id=business_id,
                action="profile_update",
                resource_type="customer",
                resource_id=customer.id,
                actor_type="system",
                metadata={"fields": ["avatar_url"], "source": f"{channel_type}_connector"},
            )
            updated += 1
        tenant_db.commit()
    return {
        "status": "synced",
        "updated": updated,
        "matchedExternalUserIds": sorted(matched_external_user_ids),
    }


def _connector_exe_path(channel_type: str) -> Path | None:
    app_name = "TikTok" if channel_type == "tiktok" else "Shopee"
    folder = "tiktok-bridge" if channel_type == "tiktok" else "shopee-bridge"
    filename = f"SmartMerchant{app_name}.exe"
    candidates = (
        Path(__file__).resolve().parents[3] / "scripts" / "dist" / folder / filename,
        Path("/app/root-scripts/dist") / folder / filename,
        Path("/app/scripts/dist") / folder / filename,
    )
    return next((path for path in candidates if path.is_file()), None)


def _validated_connector_exe(channel_type: str) -> tuple[Path, str]:
    if channel_type not in _SUPPORTED:
        raise HTTPException(status_code=404, detail="Kênh connector không được hỗ trợ.")
    app_path = _connector_exe_path(channel_type)
    if app_path is None:
        raise HTTPException(status_code=503, detail="Chưa có ứng dụng connector cho kênh này. Hãy báo quản trị viên.")
    try:
        if app_path.stat().st_size <= 1024 * 1024:
            raise HTTPException(status_code=503, detail="Ứng dụng connector trên máy chủ không hợp lệ.")
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Không thể đọc ứng dụng connector trên máy chủ.") from exc
    app_name = "TikTok" if channel_type == "tiktok" else "Shopee"
    return app_path, app_name


@router.get("/channels/{channel_type}/connector-app", dependencies=[Depends(require_admin_access)])
def download_local_connector_app(channel_type: str):
    return _connector_app_response(channel_type)


def _connector_app_response(channel_type: str, *, include_download_header: bool = True):
    app_path, app_name = _validated_connector_exe(channel_type)
    filename = f"SmartMerchant{app_name}.exe"
    archive = BytesIO()
    with ZipFile(archive, "w", compression=ZIP_STORED) as bundle:
        bundle.write(app_path, filename)
        bundle.writestr("HUONG-DAN.txt", f"Giải nén file ZIP, sau đó chạy {filename}.\n")
    headers = {"Cache-Control": "no-store"}
    if include_download_header:
        headers["Content-Disposition"] = f'attachment; filename="SmartMerchant{app_name}.zip"'
    return Response(archive.getvalue(), media_type="application/zip", headers=headers)


@router.post("/channels/{channel_type}/connector-app/download-ticket", dependencies=[Depends(require_admin_access)])
def create_connector_app_download_ticket(channel_type: str):
    _validated_connector_exe(channel_type)
    ticket = encrypt_token(
        json.dumps(
            {"purpose": "connector_app", "channel_type": channel_type, "expires_at": int(time.time()) + 300},
            separators=(",", ":"),
        ),
        settings.CHANNEL_ENCRYPTION_KEY,
    )
    return {"ticket": ticket}


@router.get("/channels/{channel_type}/connector-app/file")
def download_connector_app_with_ticket(channel_type: str, ticket: str):
    try:
        payload = json.loads(decrypt_token(ticket, settings.CHANNEL_ENCRYPTION_KEY))
        valid = (
            payload.get("purpose") == "connector_app"
            and payload.get("channel_type") == channel_type
            and int(payload.get("expires_at", 0)) > int(time.time())
        )
    except Exception:
        valid = False
    if not valid:
        raise HTTPException(status_code=404, detail="Liên kết tải file không hợp lệ hoặc đã hết hạn.")
    # This ticket route is consumed through fetch() and saved as a ZIP by the
    # browser. An attachment header lets download managers hijack that fetch.
    return _connector_app_response(channel_type, include_download_header=False)


@router.get("/channels/{channel_type}/connector-bundle", include_in_schema=False, dependencies=[Depends(require_admin_access)])
def download_local_connector_bundle_legacy(channel_type: str):
    return _connector_app_response(channel_type)
