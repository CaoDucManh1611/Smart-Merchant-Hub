import json
import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from typing import Literal

from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)

from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool

from pydantic import BaseModel, Field

from sqlalchemy import select, text
from sqlalchemy.orm import Session

import httpx
from PIL import Image

from app.core.config import settings
from app.tenancy.crm_session import get_tenant_db
from app.database.platform_session import get_platform_db
from app.db.dependencies import get_db
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.models.message_attachment import MessageAttachment
from app.services.meta_errors import MetaAPIError
from app.services.realtime import manager

from app.services.facebook_service import (
    send_facebook_message,
    send_facebook_image,
)

from app.services.instagram_service import (
    send_instagram_message,
    send_instagram_image,
)
from app.services.facebook_service import send_facebook_media
from app.services.instagram_service import send_instagram_media
from app.services.telegram_service import send_telegram_media
from app.services.zalo_service import send_zalo_media, send_zalo_message
from app.services.channel_retry import run_with_provider_retry
from app.services.channel_delivery import (
    claim_outbound_attempt,
    mark_outbound_attempt_failed,
    mark_outbound_attempt_sent,
    validate_client_id,
)
from app.services.zalo_media import normalize_zalo_audio_upload
from app.services.media_resolver import build_media_url
from app.services.audit_service import record_audit
from app.services.customer_avatar import refresh_customer_avatar_url
from app.contracts.channel_event import NormalizedAttachment, MediaType
from app.integrations.telegram import TelegramAdapter
from app.models.channel import Channel
from app.models.business import User
from app.models.conversation import Conversation
from app.models.ticket import Ticket, TicketEvent
from app.models.crm_extended import ConversationAssignment, ConversationTag, CustomerTag, Tag
from app.services.channel_credentials import decrypt_token
from app.services.ticket_sla import record_first_response
from app.auth.dependencies import require_write_access


router = APIRouter()
logger = logging.getLogger(__name__)


def _log_meta_error(exc: MetaAPIError) -> None:
    """Keep provider failures diagnosable without logging raw response data."""
    logger.warning(
        "Meta provider request failed: channel=%s stage=%s status=%s",
        exc.channel,
        exc.stage,
        exc.meta_status,
    )


# =========================================================
# UPLOAD CONFIG
# =========================================================

BASE_DIR = Path(
    __file__
).resolve().parents[2]

UPLOAD_DIR = (
    BASE_DIR
    / "uploads"
)

UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
}


MAX_IMAGE_SIZE = (
    8
    * 1024
    * 1024
)

# Media uploaded from the agent composer is stored briefly and exposed through
# the configured public base URL so channel providers can fetch it.  Provider
# adapters still enforce their own supported media types at send time.
MAX_MEDIA_UPLOAD_SIZE = 25 * 1024 * 1024
ALLOWED_MEDIA_UPLOAD_TYPES = {
    "image": {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    },
    "sticker": {
        "image/webp",
        "image/png",
        "image/jpeg",
    },
    "audio": {
        "audio/aac",
        "audio/flac",
        "audio/m4a",
        "audio/mp4",
        "audio/mpeg",
        "audio/ogg",
        "audio/opus",
        "audio/wav",
        "audio/webm",
        "application/ogg",
    },
    "video": {
        "video/mp4",
        "video/mpeg",
        "video/quicktime",
        "video/webm",
    },
    "file": {
        "application/msword",
        "application/rtf",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/x-7z-compressed",
        "application/x-rar-compressed",
        "application/pdf",
        "application/zip",
        "application/octet-stream",
        "text/csv",
        "text/plain",
    },
}


IMAGE_SIGNATURES = {
    "image/jpeg": (
        b"\xff\xd8\xff",
        ".jpg",
    ),
    "image/png": (
        b"\x89PNG\r\n\x1a\n",
        ".png",
    ),
}

NORMALIZED_IMAGE_FORMAT = "JPEG"
NORMALIZED_IMAGE_MODE = "RGB"


# =========================================================
# SCHEMA
# =========================================================

class SendMessageRequest(
    BaseModel
):
    text: str
    client_id: str | None = None


class SendMediaRequest(
    BaseModel
):
    media_url: str
    media_type: str = "image"
    caption: str | None = None
    client_id: str | None = None


class ConversationAssignmentRequest(BaseModel):
    assigned_user_id: int | None = None


class BulkConversationAssignmentRequest(BaseModel):
    conversation_ids: list[int] = Field(min_length=1, max_length=100)
    assigned_user_id: int | None = None


class BulkConversationTagUpdate(BaseModel):
    conversation_ids: list[int] = Field(min_length=1, max_length=100)
    tag_id: int = Field(gt=0)
    action: Literal["add", "remove"]


class ConversationOutcomeRequest(BaseModel):
    outcome: Literal["resolved", "needs_human", "customer_unanswered"] | None


class ConversationPriorityRequest(BaseModel):
    is_priority: bool


# =========================================================
# HELPER - PUBLIC BASE URL
# =========================================================

def get_public_base_url() -> str:
    """
    URL public của backend.

    Ví dụ:
    https://xxxx.ngrok-free.dev
    """

    base_url = str(
        settings.PUBLIC_BASE_URL
        or ""
    ).strip()

    if not base_url:

        raise HTTPException(
            status_code=500,
            detail=(
                "Chưa cấu hình "
                "PUBLIC_BASE_URL trong .env"
            ),
        )

    # Older setup instructions used the OAuth callback URL as
    # ``PUBLIC_BASE_URL``.  Media providers need the public origin, otherwise
    # uploads are exposed at paths such as ``/api/oauth/meta/callback/api/...``
    # and fail with a 404.  Keep the callback setting itself untouched and
    # normalize only the URL used to build public media URLs.
    parsed = urlsplit(base_url)
    public_path = parsed.path or ""
    if "/api/" in public_path:
        public_path = public_path.split("/api/", 1)[0]
    normalized = urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            public_path.rstrip("/"),
            "",
            "",
        )
    ).rstrip("/")
    return normalized or base_url.rstrip("/")


def detect_image_type(
    file_bytes: bytes,
) -> tuple[str, str]:
    for media_type, (
        signature,
        extension,
    ) in IMAGE_SIGNATURES.items():
        if file_bytes.startswith(
            signature
        ):
            return (
                media_type,
                extension,
            )

    raise HTTPException(
        status_code=400,
        detail=(
            "File không phải PNG/JPEG hợp lệ. "
            "Vui lòng gửi ảnh .png, .jpg hoặc .jpeg."
        ),
    )


def normalize_image_to_jpeg(
    file_bytes: bytes,
) -> tuple[bytes, dict]:
    try:
        image = Image.open(
            BytesIO(file_bytes)
        )
        image.verify()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "stage":
                    "image_verify",
                "message":
                    f"Ảnh upload không hợp lệ: {exc}",
            },
        ) from exc

    try:
        reopened = Image.open(
            BytesIO(file_bytes)
        )
        original_format = (
            reopened.format
        )
        original_mode = (
            reopened.mode
        )
        original_size = (
            reopened.size
        )

        if reopened.mode in (
            "RGBA",
            "LA",
        ) or (
            reopened.mode == "P"
            and "transparency"
            in reopened.info
        ):
            alpha_image = (
                reopened.convert(
                    "RGBA"
                )
            )
            background = Image.new(
                "RGBA",
                alpha_image.size,
                (
                    255,
                    255,
                    255,
                    255,
                ),
            )
            reopened = Image.alpha_composite(
                background,
                alpha_image,
            )

        normalized = reopened.convert(
            NORMALIZED_IMAGE_MODE
        )

        output = BytesIO()
        normalized.save(
            output,
            format=NORMALIZED_IMAGE_FORMAT,
            quality=90,
            progressive=False,
            optimize=False,
        )
        normalized_bytes = (
            output.getvalue()
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "stage":
                    "image_normalize",
                "message":
                    f"Không thể normalize ảnh: {exc}",
            },
        ) from exc

    return (
        normalized_bytes,
        {
            "original_format":
                original_format,
            "original_mode":
                original_mode,
            "original_size":
                original_size,
            "normalized_format":
                NORMALIZED_IMAGE_FORMAT,
            "normalized_mode":
                NORMALIZED_IMAGE_MODE,
        },
    )


def get_upload_file_media_type(
    file_path: Path,
) -> str:
    with file_path.open(
        "rb"
    ) as image_file:
        header = image_file.read(
            16
        )

    media_type, _ = (
        detect_image_type(
            header
        )
    )

    return media_type


def check_public_image_url(
    image_url: str,
) -> dict:
    try:
        response = httpx.get(
            image_url,
            follow_redirects=True,
            timeout=15,
        )
    except httpx.RequestError as exc:
        logger.warning("Public media URL check failed: error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=400,
            detail={
                "stage":
                    "public_url_check",
                "message":
                    "Public image URL could not be reached",
            },
        )

    content_type = (
        response.headers.get(
            "content-type",
            "",
        )
        .split(";")[0]
        .strip()
        .lower()
    )

    content_length = (
        response.headers.get(
            "content-length"
        )
    )

    logger.info("Public media URL checked: status=%s content_type=%s", response.status_code, content_type)

    if (
        response.status_code != 200
        or not content_type.startswith(
            "image/"
        )
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "stage":
                    "public_url_check",
                "message":
                    "Public image URL không trả về ảnh hợp lệ",
                "status":
                    response.status_code,
                "content_type":
                    content_type,
                "content_length":
                    content_length,
                "final_url":
                    str(response.url),
            },
        )

    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "stage":
                    "public_url_check",
                "message":
                    "Meta outbound hiện chỉ hỗ trợ PNG/JPEG ổn định",
                "content_type":
                    content_type,
            },
        )

    return {
        "status":
            response.status_code,
        "content_type":
            content_type,
        "content_length":
            content_length,
        "final_url":
            str(response.url),
    }


async def check_public_image_url_async(
    image_url: str,
) -> dict:
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=15,
        ) as client:
            response = await client.get(
                image_url
            )
    except httpx.RequestError as exc:
        logger.warning("Public media URL check failed: error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=400,
            detail={
                "stage":
                    "public_url_check",
                "message":
                    "Public image URL could not be reached",
            },
        )

    content_type = (
        response.headers.get(
            "content-type",
            "",
        )
        .split(";")[0]
        .strip()
        .lower()
    )

    content_length = (
        response.headers.get(
            "content-length"
        )
    )

    logger.info("Public media URL checked: status=%s content_type=%s", response.status_code, content_type)

    if (
        response.status_code != 200
        or not content_type.startswith(
            "image/"
        )
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "stage":
                    "public_url_check",
                "message":
                    "Public image URL không trả về ảnh hợp lệ",
                "status":
                    response.status_code,
                "content_type":
                    content_type,
                "content_length":
                    content_length,
                "final_url":
                    str(response.url),
            },
        )

    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "stage":
                    "public_url_check",
                "message":
                    "Meta outbound hiện chỉ hỗ trợ PNG/JPEG ổn định",
                "content_type":
                    content_type,
            },
        )

    return {
        "status":
            response.status_code,
        "content_type":
            content_type,
        "content_length":
            content_length,
        "final_url":
            str(response.url),
    }


async def prepare_uploaded_image(
    file: UploadFile,
    conversation_id: int,
) -> tuple[str, Path]:
    upload_content_type = (
        file.content_type
        or ""
    ).lower()

    if (
        upload_content_type
        not in ALLOWED_IMAGE_TYPES
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Chi ho tro anh "
                "JPG, JPEG hoac PNG"
            ),
        )

    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(
            status_code=400,
            detail="File anh bi rong",
        )

    if len(file_bytes) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="Anh qua lon. Toi da 8MB",
        )

    logger.info("Inbound media upload received: content_type=%s size_bytes=%s", upload_content_type, len(file_bytes))

    original_content_type, _ = detect_image_type(
        file_bytes
    )

    if original_content_type != upload_content_type:
        raise HTTPException(
            status_code=400,
            detail={
                "stage":
                    "image_validation",
                "message":
                    "Content-Type khong khop binary anh that",
                "upload_content_type":
                    upload_content_type,
                "detected_content_type":
                    original_content_type,
            },
        )

    normalized_bytes, normalize_info = (
        normalize_image_to_jpeg(
            file_bytes
        )
    )

    filename = (
        f"{uuid.uuid4().hex}.jpg"
    )

    file_path = (
        UPLOAD_DIR
        / filename
    )

    try:
        with open(
            file_path,
            "wb",
        ) as output_file:
            output_file.write(
                normalized_bytes
            )
    except Exception as exc:
        logger.error("Media upload persistence failed: error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Khong the luu file upload",
        )

    media_url = (
        f"{get_public_base_url()}"
        f"/api/conversations"
        f"/uploads/{filename}"
    )

    logger.info("Media upload normalized: format=%s size_bytes=%s", normalize_info["original_format"], len(normalized_bytes))

    await check_public_image_url_async(
        media_url
    )

    return (
        media_url,
        file_path,
    )


def meta_error_status_code(
    exc: MetaAPIError,
) -> int:
    if exc.meta_status and 400 <= exc.meta_status < 500:
        return 400

    return 502


def extract_webhook_sender_id(
    raw_payload: dict | None,
) -> str | None:
    if not isinstance(
        raw_payload,
        dict,
    ):
        return None

    entries = raw_payload.get(
        "entry",
        [],
    )

    if not entries:
        return None

    messaging = entries[0].get(
        "messaging",
        [],
    )

    if not messaging:
        return None

    return (
        messaging[0]
        .get(
            "sender",
            {},
        )
        .get(
            "id"
        )
    )


def log_instagram_recipient_audit(
    db: Session,
    conversation_id: int,
    db_external_user_id: str,
):
    latest_inbound = db.execute(
        text("""
            SELECT
                external_user_id,
                raw_payload

            FROM messages

            WHERE conversation_id = :conversation_id
              AND channel = 'instagram'
              AND direction = 'inbound'

            ORDER BY id DESC

            LIMIT 1
        """),
        {
            "conversation_id":
                conversation_id,
        },
    ).mappings().first()

    raw_payload = (
        latest_inbound["raw_payload"]
        if latest_inbound
        else None
    )

    webhook_sender_id = (
        extract_webhook_sender_id(
            raw_payload
        )
    )

    graph_from_id = (
        latest_inbound["external_user_id"]
        if latest_inbound
        else None
    )

    selected_recipient_id = str(
        db_external_user_id
        or ""
    ).strip()

    logger.info(
        "Instagram recipient audit: webhook_identity_present=%s "
        "conversation_identity_matches_webhook=%s",
        bool(webhook_sender_id or graph_from_id),
        bool(selected_recipient_id and selected_recipient_id in {webhook_sender_id, graph_from_id}),
    )


# =========================================================
# HELPER - GET CONVERSATION
# =========================================================

def get_conversation_target(
    db: Session,
    conversation_id: int,
    business_id: int | None = None,
):
    """
    Lấy conversation
    và external_user_id khách.
    """

    conversation = db.execute(
        text("""
            SELECT
                cv.id,
                cv.channel,
                cv.channel_id,
                cv.customer_id,
                cv.assigned_user_id,
                c.external_user_id

            FROM conversations cv

            JOIN customers c
                ON c.id = cv.customer_id

            WHERE
                cv.id = :conversation_id
                AND (:business_id IS NULL OR cv.business_id = :business_id)
                AND (:business_id IS NULL OR c.business_id = :business_id)

            LIMIT 1
        """),
        {
            "conversation_id": conversation_id,
            "business_id": business_id,
        },
    ).mappings().first()


    if conversation is None:

        raise HTTPException(
            status_code=404,
            detail=(
                "Conversation not found"
            ),
        )


    if not conversation[
        "external_user_id"
    ]:

        raise HTTPException(
            status_code=400,
            detail=(
                "Customer không có "
                "external_user_id"
            ),
        )


    return conversation


def require_responsible_staff(
    conversation: dict,
    actor: User | None,
) -> None:
    """Allow customer replies only from the employee responsible for a chat.

    Every staff account in a shop may still read the unified inbox. Once a
    conversation has an assignee, however, another employee cannot send a
    customer message under that person's responsibility. The check is at the
    API boundary, so it cannot be bypassed through the browser.
    """
    assigned_user_id = conversation.get("assigned_user_id")
    if assigned_user_id is None:
        return
    if actor is None:
        raise HTTPException(status_code=401, detail="Cần đăng nhập để trả lời hội thoại đã phân công.")
    if int(actor.id) != int(assigned_user_id):
        raise HTTPException(
            status_code=403,
            detail="Hội thoại này đang do nhân viên phụ trách trả lời. Bạn vẫn có thể xem toàn bộ nội dung.",
        )


def send_telegram_text(
    *,
    db: Session,
    conversation: dict,
    recipient_id: str,
    text_content: str,
    business_id: int,
) -> tuple[dict, Channel]:
    """Send through the conversation's tenant-owned Telegram channel.

    A conversation must retain the channel connection that received it.  This
    prevents a missing/old channel link from silently falling back to a global
    environment token or another active bot in the same tenant.
    """
    channel_id = conversation.get("channel_id")
    if channel_id is None:
        raise HTTPException(
            status_code=409,
            detail="Telegram conversation is not linked to a channel connection",
        )

    channel = db.scalar(
        select(Channel).where(
            Channel.id == int(channel_id),
            Channel.business_id == business_id,
            Channel.channel_type == "telegram",
            Channel.status == "active",
        )
    )
    if channel is None:
        raise HTTPException(
            status_code=404,
            detail="Active Telegram channel not found for this tenant",
        )
    if not channel.access_token_encrypted:
        raise HTTPException(
            status_code=503,
            detail="Telegram channel credentials are not configured",
        )

    try:
        access_token = decrypt_token(
            channel.access_token_encrypted,
            settings.CHANNEL_ENCRYPTION_KEY,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Telegram channel credentials could not be decrypted",
        ) from exc

    try:
        result = run_with_provider_retry(
            provider="telegram",
            operation="text_send",
            request=lambda: TelegramAdapter().send_message(
                recipient_external_id=recipient_id,
                text=text_content,
                access_token=access_token,
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Telegram provider could not be reached",
        ) from exc
    if result.get("ok") is False:
        description = result.get("description") or "Telegram rejected the message"
        raise HTTPException(status_code=502, detail=description)
    return result, channel


def _local_connector_thread_id(db: Session, conversation_id: int, channel: str) -> str:
    """Recover the platform conversation id saved by a local connector."""
    row = db.execute(
        text("""
            SELECT raw_payload
            FROM messages
            WHERE conversation_id = :conversation_id
              AND channel = :channel
              AND direction = 'inbound'
            ORDER BY id DESC
            LIMIT 1
        """),
        {"conversation_id": conversation_id, "channel": channel},
    ).first()
    raw = row[0] if row else None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        return ""
    return str(raw.get("threadId") or raw.get("thread_id") or raw.get("conv_id") or "").strip()


def send_tiktok_text(
    *,
    db: Session,
    conversation: dict,
    recipient_id: str,
    text_content: str,
    business_id: int,
) -> tuple[dict, Channel]:
    """Ask the local ReLttk bridge to send a message on this conversation."""
    channel_id = conversation.get("channel_id")
    if channel_id is None:
        raise HTTPException(status_code=409, detail="TikTok conversation is not linked to a channel connection")

    channel = db.scalar(
        select(Channel).where(
            Channel.id == int(channel_id),
            Channel.business_id == business_id,
            Channel.channel_type == "tiktok",
            Channel.status == "active",
        )
    )
    if channel is None:
        raise HTTPException(status_code=404, detail="Active TikTok channel not found for this tenant")

    config = channel.config if isinstance(channel.config, dict) else {}
    encrypted_secret = config.get("webhook_secret_encrypted")
    try:
        if encrypted_secret:
            bridge_secret = decrypt_token(str(encrypted_secret), settings.CHANNEL_ENCRYPTION_KEY)
        elif channel.access_token_encrypted:
            bridge_secret = decrypt_token(channel.access_token_encrypted, settings.CHANNEL_ENCRYPTION_KEY)
        else:
            bridge_secret = ""
    except Exception as exc:
        raise HTTPException(status_code=503, detail="TikTok bridge credentials could not be decrypted") from exc
    if not bridge_secret:
        raise HTTPException(status_code=503, detail="TikTok bridge credentials are not configured")

    thread_id = _local_connector_thread_id(db, int(conversation["id"]), "tiktok")
    if not thread_id:
        raise HTTPException(status_code=409, detail="TikTok conversation chưa có thread_id để gửi tin")

    # Prefer the current runtime setting over the URL persisted when the
    # channel was connected.  The launcher uses 127.0.0.1 for a host-run
    # FastAPI process, while Docker uses host.docker.internal; a stale value
    # in channel.config must not make an otherwise healthy bridge unreachable.
    control_url = str(
        settings.TIKTOK_BRIDGE_CONTROL_URL or config.get("bridge_control_url") or ""
    ).strip().rstrip("/")
    if not control_url:
        raise HTTPException(status_code=503, detail="TikTok outbound bridge chưa được cấu hình")

    try:
        response = httpx.post(
            f"{control_url}/send",
            json={
                "threadId": thread_id,
                "message": text_content or "",
                "conversationId": int(conversation["id"]),
                "recipientId": str(recipient_id or ""),
            },
            headers={"X-TikTok-Bridge-Secret": bridge_secret},
            timeout=30,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Không thể kết nối TikTok bridge. Hãy khởi động bot TikTok và kiểm tra cổng 8091.",
        ) from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        raise HTTPException(
            status_code=502 if response.status_code >= 500 else response.status_code,
            detail=detail or "TikTok bridge từ chối gửi tin",
        )
    if not isinstance(payload, dict):
        payload = {"status": "sent", "message_id": f"tiktok-bridge:{thread_id}"}
    return payload, channel


def send_shopee_text(
    *,
    db: Session,
    conversation: dict,
    recipient_id: str,
    text_content: str,
    business_id: int,
) -> tuple[dict, Channel]:
    """Send via the Shopee connector attached to the shop's local Edge session."""
    channel_id = conversation.get("channel_id")
    channel = db.scalar(
        select(Channel).where(
            Channel.id == int(channel_id or 0),
            Channel.business_id == business_id,
            Channel.channel_type == "shopee",
            Channel.status == "active",
        )
    )
    if channel is None or not channel.access_token_encrypted:
        raise HTTPException(status_code=503, detail="Shopee connector chưa được ghép nối.")

    thread_id = _local_connector_thread_id(db, int(conversation["id"]), "shopee")
    if not thread_id:
        raise HTTPException(status_code=409, detail="Shopee conversation chưa có thread_id để gửi tin")
    try:
        connector_token = decrypt_token(channel.access_token_encrypted, settings.CHANNEL_ENCRYPTION_KEY)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Shopee connector credentials could not be decrypted") from exc

    control_url = str(settings.SHOPEE_BRIDGE_CONTROL_URL or "").strip().rstrip("/")
    if not control_url:
        raise HTTPException(status_code=503, detail="Shopee outbound connector chưa được cấu hình")
    try:
        response = httpx.post(
            f"{control_url}/send",
            json={"threadId": thread_id, "message": text_content or "", "recipientId": str(recipient_id or "")},
            headers={"X-Shopee-Bridge-Secret": connector_token},
            timeout=30,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Không thể kết nối Shopee connector. Hãy mở SmartMerchantShopee trên máy đang đăng nhập Shopee.",
        ) from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        raise HTTPException(status_code=response.status_code, detail=detail or "Shopee connector từ chối gửi tin")
    return payload if isinstance(payload, dict) else {"status": "sent"}, channel


def telegram_external_message_id(result: dict, channel: Channel) -> str | None:
    """Build a collision-resistant local id from Telegram's response."""
    message_id = result.get("message_id")
    if message_id is None:
        message_id = (result.get("result") or {}).get("message_id")
    if message_id is None:
        return None
    return f"telegram:{channel.external_account_id}:{message_id}"


# =========================================================
# HELPER - SAVE OUTBOUND MESSAGE
# =========================================================

def save_outbound_message(
    db: Session,
    conversation_id: int,
    channel: str,
    recipient_id: str,
    external_message_id: str | None,
    content: str | None,
    media_type: str | None,
    media_url: str | None,
    meta_response: dict,
    sender_type: str = "staff",
    sender_user_id: int | None = None,
):
    """
    Lưu outbound message
    vào PostgreSQL.
    """

    result = db.execute(
        text("""
            INSERT INTO messages (
                conversation_id,
                channel,
                external_user_id,
                external_message_id,
                sender_type,
                sender_user_id,
                direction,
                content,
                media_type,
                media_url,
                raw_payload
            )

            VALUES (
                :conversation_id,
                :channel,
                :external_user_id,
                :external_message_id,
                :sender_type,
                :sender_user_id,
                'outbound',
                :content,
                :media_type,
                :media_url,

                CAST(
                    :raw_payload
                    AS JSONB
                )
            )

            ON CONFLICT (
                external_message_id
            )

            DO NOTHING
            RETURNING
                id AS message_id,
                conversation_id,
                channel,
                external_user_id,
                external_message_id,
                direction,
                content,
                media_type,
                media_url,
                raw_payload,
                received_at
        """),
        {
            "conversation_id":
                conversation_id,

            "channel":
                channel,

            "external_user_id":
                recipient_id,

            "external_message_id":
                external_message_id,

            "sender_type": sender_type,

            "sender_user_id": sender_user_id,

            "content":
                content,

            "media_type":
                media_type,

            "media_url":
                media_url,

            "raw_payload":
                json.dumps(
                    {
                        "direction":
                            "outbound",

                        "type":
                            media_type
                            or "text",

                        "meta_response":
                            meta_response,
                    }
                ),
        },
    )

    # Consume INSERT ... RETURNING before committing. SQLite keeps the
    # statement cursor active until it is read, which otherwise causes
    # ``cannot commit transaction - SQL statements in progress``.
    row = result.mappings().first()

    def mark_first_response() -> None:
        if sender_type != "staff":
            return
        business_id = db.query(Conversation.business_id).filter(
            Conversation.id == conversation_id,
        ).scalar()
        if business_id is not None:
            record_first_response(
                db,
                conversation_id,
                int(business_id),
                datetime.now(timezone.utc).replace(tzinfo=None),
            )

    if row:
        mark_first_response()
        db.commit()
        return dict(
            row
        )

    db.commit()

    existing = db.execute(
        text("""
            SELECT
                id AS message_id,
                conversation_id,
                channel,
                external_user_id,
                external_message_id,
                direction,
                content,
                media_type,
                media_url,
                raw_payload,
                received_at

            FROM messages

            WHERE external_message_id = :external_message_id

            LIMIT 1
        """),
        {
            "external_message_id":
                external_message_id,
        },
    ).mappings().first()

    if existing:
        mark_first_response()
        db.commit()
        return dict(
            existing
        )

    return None


async def broadcast_message_created(
    message: dict | None,
    *,
    business_id: int | None,
):
    if not message or business_id is None:
        return

    await manager.broadcast(
        {
            "type":
                "message_created",
            "conversation_id":
                message.get(
                    "conversation_id"
                ),
            "message":
                message,
        },
        business_id=int(business_id),
    )


def _claim_outbound_delivery(
    db: Session,
    *,
    client_id: str | None,
    channel_id: int | None,
    business_id: int,
    conversation_id: int,
) -> tuple[int, dict | None]:
    key = validate_client_id(client_id)
    state, attempt = claim_outbound_attempt(
        db,
        channel_id=channel_id,
        business_id=business_id,
        conversation_id=conversation_id,
        client_id=key,
    )
    if state == "sent":
        message = None
        if attempt.message_id is not None:
            message = db.execute(
                text("""
                    SELECT id AS message_id, conversation_id, channel, external_user_id,
                           external_message_id, direction, content, media_type, media_url,
                           raw_payload, received_at
                    FROM messages WHERE id = :message_id LIMIT 1
                """),
                {"message_id": attempt.message_id},
            ).mappings().first()
        if message:
            return attempt.id, dict(message)
        state = "sent_without_message"
    if state != "claimed":
        detail = {
            "code": f"delivery_{state}",
            "message": (
                "Tin nhắn đã được gửi trước đó."
                if state == "sent_without_message"
                else "Chưa thể gửi lại an toàn. Hãy kiểm tra trạng thái trên kênh trước."
                if state == "unknown"
                else "Tin nhắn đang được xử lý hoặc khóa gửi bị trùng."
            ),
        }
        raise HTTPException(status_code=409, detail=detail)
    return attempt.id, None


async def send_idempotent_outbound(
    db: Session,
    *,
    client_id: str | None,
    channel_id: int | None,
    business_id: int,
    conversation_id: int,
    channel: str,
    recipient_id: str,
    text_content: str | None = None,
    image_url: str | None = None,
    sender_user_id: int | None = None,
) -> dict:
    attempt_id, replay = _claim_outbound_delivery(
        db,
        client_id=client_id,
        channel_id=channel_id,
        business_id=business_id,
        conversation_id=conversation_id,
    )
    if replay:
        return {
            "success": True,
            "message_id": replay.get("external_message_id"),
            "message": replay,
            "meta_response": {"idempotent_replay": True},
        }
    try:
        result = await send_and_save_outbound(
            db=db,
            conversation_id=conversation_id,
            channel=channel,
            recipient_id=recipient_id,
            text_content=text_content,
            image_url=image_url,
            business_id=business_id,
            sender_user_id=sender_user_id,
        )
    except Exception as exc:
        try:
            mark_outbound_attempt_failed(db, attempt_id, exc)
        except Exception:
            db.rollback()
            logger.error("Could not persist outbound delivery state: error_type=%s", type(exc).__name__)
        raise
    if not result.get("message"):
        mark_outbound_attempt_failed(
            db, attempt_id, HTTPException(status_code=502, detail="Message persistence failed after provider send")
        )
        raise HTTPException(status_code=502, detail="Không xác nhận được trạng thái lưu tin nhắn; vui lòng kiểm tra kênh trước khi gửi lại.")
    mark_outbound_attempt_sent(
        db,
        attempt_id,
        message_id=result["message"].get("message_id"),
    )
    return result


async def send_and_save_outbound(
    db: Session,
    conversation_id: int,
    channel: str,
    recipient_id: str,
    text_content: str | None = None,
    image_url: str | None = None,
    business_id: int | None = None,
    sender_user_id: int | None = None,
) -> dict:
    if image_url:
        logger.info("Outbound channel send started: channel=%s operation=image", channel)

        if channel == "facebook":
            result = await run_in_threadpool(
                send_facebook_image,
                recipient_id=recipient_id,
                image_url=image_url,
                db=db,
                business_id=business_id,
            )
        elif channel == "instagram":
            result = await run_in_threadpool(
                send_instagram_image,
                recipient_id=recipient_id,
                image_url=image_url,
                db=db,
                business_id=business_id,
            )
        elif channel == "telegram":
            if business_id is None:
                raise HTTPException(status_code=400, detail="Tenant context is required")
            result = await run_in_threadpool(
                send_telegram_media,
                db=db,
                business_id=business_id,
                conversation_id=conversation_id,
                recipient_id=recipient_id,
                media_type="image",
                media_url=image_url,
                caption=None,
            )
        elif channel == "zalo":
            if business_id is None:
                raise HTTPException(status_code=400, detail="Tenant context is required")
            result = await run_in_threadpool(
                send_zalo_media,
                db=db,
                business_id=business_id,
                conversation_id=conversation_id,
                recipient_id=recipient_id,
                media_type="image",
                media_url=image_url,
                caption=None,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported channel: {channel}",
            )

        external_message_id = result.get(
            "message_id"
        )

        saved_message = save_outbound_message(
            db=db,
            conversation_id=conversation_id,
            channel=channel,
            recipient_id=recipient_id,
            external_message_id=external_message_id,
            content=None,
            media_type="image",
            media_url=image_url,
            meta_response=result,
            sender_type="staff",
            sender_user_id=sender_user_id,
        )

    else:
        logger.info("Outbound channel send started: channel=%s operation=text", channel)

        if channel == "facebook":
            result = await run_in_threadpool(
                send_facebook_message,
                recipient_id=recipient_id,
                text=text_content or "",
                db=db,
                business_id=business_id,
            )
        elif channel == "instagram":
            result = await run_in_threadpool(
                send_instagram_message,
                recipient_id=recipient_id,
                text=text_content or "",
                db=db,
                business_id=business_id,
            )
        elif channel == "telegram":
            if business_id is None:
                raise HTTPException(status_code=400, detail="Tenant context is required")
            telegram_conversation = get_conversation_target(
                db=db,
                conversation_id=conversation_id,
                business_id=business_id,
            )
            result, telegram_channel = await run_in_threadpool(
                send_telegram_text,
                db=db,
                conversation=telegram_conversation,
                recipient_id=recipient_id,
                text_content=text_content or "",
                business_id=business_id,
            )
            external_message_id = telegram_external_message_id(result, telegram_channel)
        elif channel == "tiktok":
            if business_id is None:
                raise HTTPException(status_code=400, detail="Tenant context is required")
            tiktok_conversation = get_conversation_target(
                db=db,
                conversation_id=conversation_id,
                business_id=business_id,
            )
            result, _ = await run_in_threadpool(
                send_tiktok_text,
                db=db,
                conversation=tiktok_conversation,
                recipient_id=recipient_id,
                text_content=text_content or "",
                business_id=business_id,
            )
        elif channel == "shopee":
            if business_id is None:
                raise HTTPException(status_code=400, detail="Tenant context is required")
            shopee_conversation = get_conversation_target(
                db=db,
                conversation_id=conversation_id,
                business_id=business_id,
            )
            result, _ = await run_in_threadpool(
                send_shopee_text,
                db=db,
                conversation=shopee_conversation,
                recipient_id=recipient_id,
                text_content=text_content or "",
                business_id=business_id,
            )
        elif channel == "zalo":
            if business_id is None:
                raise HTTPException(status_code=400, detail="Tenant context is required")
            result = await run_in_threadpool(
                send_zalo_message,
                db=db,
                business_id=business_id,
                conversation_id=conversation_id,
                recipient_id=recipient_id,
                text=text_content or "",
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported channel: {channel}",
            )

        if channel != "telegram":
            external_message_id = result.get(
                "message_id"
            )

        saved_message = save_outbound_message(
            db=db,
            conversation_id=conversation_id,
            channel=channel,
            recipient_id=recipient_id,
            external_message_id=external_message_id,
            content=text_content,
            media_type=None,
            media_url=None,
            meta_response=result,
            sender_type="staff",
            sender_user_id=sender_user_id,
        )

    logger.info("Outbound channel send succeeded: channel=%s", channel)

    await broadcast_message_created(
        saved_message,
        business_id=business_id,
    )

    return {
        "success":
            True,
        "message_id":
            external_message_id,
        "message":
            saved_message,
        "meta_response":
            result,
    }


# =========================================================
# GET CONVERSATIONS
# =========================================================

@router.get("")
def get_conversations(
    limit: int | None = Query(default=None, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    customer_id: int | None = Query(default=None, ge=1),
    unassigned_only: bool = Query(default=False),
    db: Session = Depends(
        get_tenant_db
    ),
    tenant: TenantContext = Depends(get_tenant_context),
):

    customer_filter = "\n          AND cv.customer_id = :customer_id" if customer_id is not None else ""
    assignment_filter = "\n          AND cv.assigned_user_id IS NULL" if unassigned_only else ""
    query_sql = f"""
        SELECT
            cv.id AS conversation_id,
            cv.customer_id,

            c.external_user_id,
            c.name AS customer_name,
            c.email AS customer_email,
            c.phone AS customer_phone,
            c.avatar_url,

            cv.channel,
            cv.status,
            cv.bot_mode,
            cv.resolution_outcome,
            COALESCE(cv.priority, 'normal') AS priority,
            cv.assigned_user_id,
            cv.created_at,
            cv.updated_at,

            (
                SELECT
                    m.content

                FROM messages m

                WHERE
                    m.conversation_id
                    = cv.id

                ORDER BY
                    m.id DESC

                LIMIT 1
            ) AS last_message,

            (
                SELECT
                    m.direction

                FROM messages m

                WHERE
                    m.conversation_id
                    = cv.id

                ORDER BY
                    m.id DESC

                LIMIT 1
            ) AS last_message_direction,

            (
                SELECT
                    m.media_type

                FROM messages m

                WHERE
                    m.conversation_id
                    = cv.id

                ORDER BY
                    m.id DESC

                LIMIT 1
            ) AS last_media_type,

            (
                SELECT
                    m.media_url

                FROM messages m

                WHERE
                    m.conversation_id
                    = cv.id

                ORDER BY
                    m.id DESC

                LIMIT 1
            ) AS last_media_url,

            (
                SELECT
                    m.received_at

                FROM messages m

                WHERE
                    m.conversation_id
                    = cv.id

                ORDER BY
                    m.id DESC

                LIMIT 1
            ) AS last_message_at,

            (
                SELECT COUNT(*)
                FROM messages m
                WHERE m.conversation_id = cv.id
                  AND m.direction = 'inbound'
                  AND COALESCE(m.status, 'received') != 'read'
            ) AS unread_count,

            (
                SELECT COUNT(*)
                FROM orders o
                WHERE o.conversation_id = cv.id
                  AND o.business_id = :business_id
                  AND o.status = 'pending_confirmation'
            ) AS pending_order_confirmation_count

        FROM conversations cv

        JOIN customers c
            ON c.id = cv.customer_id
           AND c.business_id = :business_id

        WHERE cv.business_id = :business_id
          {customer_filter}
          {assignment_filter}

        ORDER BY
            last_message_at DESC
            NULLS LAST
    """

    params = {"business_id": tenant.business_id}
    if customer_id is not None:
        params["customer_id"] = customer_id
    if limit is not None:
        query_sql += "\n LIMIT :limit OFFSET :offset"
        params.update({"limit": limit, "offset": offset})

    result = db.execute(text(query_sql), params).mappings().all()
    total_sql = """
        SELECT COUNT(*) FROM conversations
        WHERE business_id = :business_id
    """
    if unassigned_only:
        total_sql += "\n          AND assigned_user_id IS NULL"
    total_params = {"business_id": tenant.business_id}
    if customer_id is not None:
        total_sql += "\n          AND customer_id = :customer_id"
        total_params["customer_id"] = customer_id
    total = int(db.execute(text(total_sql), total_params).scalar_one())

    customer_ids = {int(row["customer_id"]) for row in result if row.get("customer_id") is not None}
    tag_map: dict[int, list[str]] = {customer_id: [] for customer_id in customer_ids}
    if customer_ids:
        tag_rows = db.query(CustomerTag.customer_id, Tag.name).join(
            Tag, Tag.id == CustomerTag.tag_id
        ).filter(
            CustomerTag.business_id == tenant.business_id,
            Tag.business_id == tenant.business_id,
            CustomerTag.customer_id.in_(customer_ids),
        ).order_by(Tag.name.asc()).all()
        for customer_id, tag_name in tag_rows:
            tag_map.setdefault(int(customer_id), []).append(tag_name)

    conversation_ids = {int(row["conversation_id"]) for row in result}
    conversation_tag_map: dict[int, list[str]] = {conversation_id: [] for conversation_id in conversation_ids}
    if conversation_ids:
        tag_rows = db.query(ConversationTag.conversation_id, Tag.name).join(
            Tag, Tag.id == ConversationTag.tag_id
        ).filter(
            ConversationTag.conversation_id.in_(conversation_ids),
            Tag.business_id == tenant.business_id,
        ).order_by(Tag.name.asc()).all()
        for conversation_id, tag_name in tag_rows:
            conversation_tag_map.setdefault(int(conversation_id), []).append(tag_name)

    items = [
            {
                **dict(row),
                "avatar_url": refresh_customer_avatar_url(
                    row.get("avatar_url"),
                    customer_id=int(row["customer_id"]),
                    business_id=tenant.business_id,
                    channel=row.get("channel"),
                ),
                "customer_tags": tag_map.get(int(row["customer_id"]), []),
                "conversation_tags": conversation_tag_map.get(int(row["conversation_id"]), []),
            }
            for row in result
        ]

    return {
        "items": items,
        "total": total,
        "has_more": limit is not None and offset + len(items) < total,
        "next_offset": offset + len(items),
    }


@router.post("/{conversation_id}/mark-read", dependencies=[Depends(require_write_access)])
def mark_conversation_read(
    conversation_id: int,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    """Mark only this tenant's inbound messages as read.

    Read receipts are an inbox concern, not a provider delivery acknowledgement:
    Meta, Telegram and Zalo do not share one portable remote-read API.  Keeping
    the status locally makes the unified Inbox deterministic and idempotent.
    """
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == tenant.business_id,
    ).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation không tồn tại.")

    result = db.execute(
        text(
            """
            UPDATE messages
            SET status = 'read'
            WHERE conversation_id = :conversation_id
              AND direction = 'inbound'
              AND COALESCE(status, 'received') != 'read'
            """
        ),
        {"conversation_id": conversation.id},
    )
    marked_count = max(0, int(result.rowcount or 0))
    if marked_count:
        record_audit(
            db,
            business_id=tenant.business_id,
            user_id=actor.id if actor else None,
            action="conversation_mark_read",
            resource_type="conversation",
            resource_id=conversation.id,
            metadata={"marked_count": marked_count},
        )
    db.commit()
    return {
        "conversation_id": conversation.id,
        "marked_count": marked_count,
        "status": "read",
    }


@router.patch("/{conversation_id}/outcome", dependencies=[Depends(require_write_access)])
def set_conversation_outcome(
    conversation_id: int,
    payload: ConversationOutcomeRequest,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == tenant.business_id,
    ).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation không tồn tại.")

    previous = conversation.resolution_outcome
    if previous != payload.outcome:
        conversation.resolution_outcome = payload.outcome
        conversation.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        record_audit(
            db,
            business_id=tenant.business_id,
            user_id=actor.id if actor else None,
            action="conversation_outcome_recorded",
            resource_type="conversation",
            resource_id=conversation.id,
            metadata={"from": previous, "to": payload.outcome},
        )
        db.commit()

    return {"conversation_id": conversation.id, "resolution_outcome": conversation.resolution_outcome}


@router.patch("/{conversation_id}/priority", dependencies=[Depends(require_write_access)])
def set_conversation_priority(
    conversation_id: int,
    payload: ConversationPriorityRequest,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == tenant.business_id,
    ).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation không tồn tại.")

    next_priority = "high" if payload.is_priority else "normal"
    previous_priority = conversation.priority or "normal"
    if previous_priority != next_priority:
        conversation.priority = next_priority
        conversation.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        record_audit(
            db,
            business_id=tenant.business_id,
            user_id=actor.id if actor else None,
            action="conversation_priority_changed",
            resource_type="conversation",
            resource_id=conversation.id,
            metadata={"from": previous_priority, "to": next_priority},
        )
        db.commit()
    return {"conversation_id": conversation.id, "priority": conversation.priority or "normal"}


@router.patch("/{conversation_id}/assignment", dependencies=[Depends(require_write_access)])
def reassign_conversation(
    conversation_id: int,
    payload: ConversationAssignmentRequest,
    db: Session = Depends(get_tenant_db),
    platform_db: Session = Depends(get_platform_db),
    user_db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == tenant.business_id,
    ).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation không tồn tại.")

    if payload.assigned_user_id is not None:
        assignee = user_db.query(User).filter(
            User.id == payload.assigned_user_id,
            User.business_id == tenant.business_id,
            User.is_active.is_(True),
        ).first()
        if assignee is None:
            raise HTTPException(status_code=404, detail="Nhân viên không thuộc business hoặc đã bị vô hiệu hóa.")

    previous_user_id = conversation.assigned_user_id
    if previous_user_id != payload.assigned_user_id:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        active_assignments = db.query(ConversationAssignment).join(
            Conversation,
            Conversation.id == ConversationAssignment.conversation_id,
        ).filter(
            ConversationAssignment.conversation_id == conversation.id,
            Conversation.business_id == tenant.business_id,
            ConversationAssignment.unassigned_at.is_(None),
        ).all()
        for assignment in active_assignments:
            assignment.unassigned_at = now
        if payload.assigned_user_id is not None:
            db.add(ConversationAssignment(
                conversation_id=conversation.id,
                user_id=payload.assigned_user_id,
                assigned_by=actor.id if actor else None,
                assignment_type="manual",
                assigned_at=now,
            ))
        conversation.assigned_user_id = payload.assigned_user_id
        record_audit(
            db,
            business_id=tenant.business_id,
            user_id=actor.id if actor else None,
            action="conversation_assignment",
            resource_type="conversation",
            resource_id=conversation.id,
            metadata={
                "previous_user_id": previous_user_id,
                "assigned_user_id": payload.assigned_user_id,
            },
        )
        db.commit()

    return {
        "conversation_id": conversation.id,
        "business_id": conversation.business_id,
        "assigned_user_id": conversation.assigned_user_id,
    }


@router.patch("/bulk-assignment", dependencies=[Depends(require_write_access)])
def bulk_reassign_conversations(
    payload: BulkConversationAssignmentRequest,
    db: Session = Depends(get_tenant_db),
    user_db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    conversation_ids = payload.conversation_ids
    if any(conversation_id <= 0 for conversation_id in conversation_ids) or len(set(conversation_ids)) != len(conversation_ids):
        raise HTTPException(status_code=422, detail="Danh sách hội thoại không hợp lệ hoặc bị trùng.")

    if payload.assigned_user_id is not None:
        assignee = user_db.query(User).filter(
            User.id == payload.assigned_user_id,
            User.business_id == tenant.business_id,
            User.is_active.is_(True),
        ).first()
        if assignee is None:
            raise HTTPException(status_code=404, detail="Nhân viên không thuộc business hoặc đã bị vô hiệu hóa.")

    conversations = db.query(Conversation).filter(
        Conversation.id.in_(conversation_ids),
        Conversation.business_id == tenant.business_id,
    ).with_for_update().all()
    if len(conversations) != len(conversation_ids):
        raise HTTPException(status_code=404, detail="Một hoặc nhiều hội thoại không tồn tại trong shop này.")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    active_assignments = db.query(ConversationAssignment).join(
        Conversation,
        Conversation.id == ConversationAssignment.conversation_id,
    ).filter(
        ConversationAssignment.conversation_id.in_(conversation_ids),
        ConversationAssignment.unassigned_at.is_(None),
        Conversation.business_id == tenant.business_id,
    ).all()
    assignments_by_conversation: dict[int, list[ConversationAssignment]] = {}
    for assignment in active_assignments:
        assignments_by_conversation.setdefault(assignment.conversation_id, []).append(assignment)

    changed_count = 0
    for conversation in conversations:
        if conversation.assigned_user_id == payload.assigned_user_id:
            continue
        for assignment in assignments_by_conversation.get(conversation.id, []):
            assignment.unassigned_at = now
        if payload.assigned_user_id is not None:
            db.add(ConversationAssignment(
                conversation_id=conversation.id,
                user_id=payload.assigned_user_id,
                assigned_by=actor.id if actor else None,
                assignment_type="manual",
                assigned_at=now,
            ))
        previous_user_id = conversation.assigned_user_id
        conversation.assigned_user_id = payload.assigned_user_id
        conversation.updated_at = now
        record_audit(
            db,
            business_id=tenant.business_id,
            user_id=actor.id if actor else None,
            action="conversation_assignment",
            resource_type="conversation",
            resource_id=conversation.id,
            metadata={
                "previous_user_id": previous_user_id,
                "assigned_user_id": payload.assigned_user_id,
                "bulk": True,
            },
        )
        changed_count += 1

    db.commit()
    return {
        "changed_count": changed_count,
        "items": [
            {"conversation_id": conversation.id, "assigned_user_id": conversation.assigned_user_id}
            for conversation in conversations
        ],
    }


@router.patch("/bulk-tags", dependencies=[Depends(require_write_access)])
def bulk_update_conversation_tags(
    payload: BulkConversationTagUpdate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    conversation_ids = payload.conversation_ids
    if any(conversation_id <= 0 for conversation_id in conversation_ids) or len(set(conversation_ids)) != len(conversation_ids):
        raise HTTPException(status_code=422, detail="Danh sách hội thoại không hợp lệ hoặc bị trùng.")

    conversations = db.query(Conversation).filter(
        Conversation.id.in_(conversation_ids),
        Conversation.business_id == tenant.business_id,
    ).with_for_update().all()
    if len(conversations) != len(conversation_ids):
        raise HTTPException(status_code=404, detail="Một hoặc nhiều hội thoại không tồn tại trong shop này.")
    tag = db.query(Tag).filter(
        Tag.id == payload.tag_id,
        Tag.business_id == tenant.business_id,
    ).first()
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag không tồn tại trong shop này.")

    links = db.query(ConversationTag).filter(
        ConversationTag.conversation_id.in_(conversation_ids),
        ConversationTag.tag_id == tag.id,
    ).all()
    links_by_conversation = {link.conversation_id: link for link in links}
    changed_ids = []
    for conversation in conversations:
        link = links_by_conversation.get(conversation.id)
        if (link is not None) == (payload.action == "add"):
            continue
        if payload.action == "add":
            db.add(ConversationTag(
                conversation_id=conversation.id,
                tag_id=tag.id,
                created_by=actor.id if actor else None,
            ))
        else:
            db.delete(link)
        record_audit(
            db,
            business_id=tenant.business_id,
            user_id=actor.id if actor else None,
            action="conversation_tag_add" if payload.action == "add" else "conversation_tag_remove",
            resource_type="conversation",
            resource_id=conversation.id,
            metadata={"tag_id": tag.id, "tag": tag.name, "bulk": True},
        )
        changed_ids.append(conversation.id)

    db.commit()
    return {"action": payload.action, "tag_id": tag.id, "changed_count": len(changed_ids), "changed_ids": changed_ids}


@router.get("/{conversation_id}/assignments")
def get_conversation_assignments(
    conversation_id: int,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == tenant.business_id,
    ).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation không tồn tại.")
    assignments = db.query(ConversationAssignment).join(
        Conversation,
        Conversation.id == ConversationAssignment.conversation_id,
    ).filter(
        ConversationAssignment.conversation_id == conversation.id,
        Conversation.business_id == tenant.business_id,
    ).order_by(ConversationAssignment.assigned_at.asc(), ConversationAssignment.id.asc()).all()
    return {
        "items": [
            {
                "id": assignment.id,
                "conversation_id": assignment.conversation_id,
                "user_id": assignment.user_id,
                "assigned_by": assignment.assigned_by,
                "assignment_type": assignment.assignment_type,
                "assigned_at": assignment.assigned_at,
                "unassigned_at": assignment.unassigned_at,
            }
            for assignment in assignments
        ],
        "total": len(assignments),
    }


# =========================================================
# GET MESSAGES
# =========================================================

@router.get(
    "/{conversation_id}/messages"
)
def get_conversation_messages(
    conversation_id: int,
    db: Session = Depends(
        get_tenant_db
    ),
    tenant: TenantContext = Depends(get_tenant_context),
):

    conversation = db.execute(
        text("""
            SELECT id

            FROM conversations

            WHERE
                id = :conversation_id
                AND business_id = :business_id

            LIMIT 1
        """),
        {
            "conversation_id": conversation_id,
            "business_id": tenant.business_id,
        },
    ).first()


    if conversation is None:

        raise HTTPException(
            status_code=404,
            detail=(
                "Conversation not found"
            ),
        )


    query = text("""
        SELECT
            m.id AS message_id,
            m.conversation_id,
            m.channel,
            m.external_user_id,
            m.external_message_id,
            m.sender_type,
            m.direction,
            m.content,
            m.media_type,
            m.media_url,
            m.raw_payload,
            m.received_at

        FROM messages m

        WHERE
            m.conversation_id
            = :conversation_id

            AND EXISTS (
                SELECT 1 FROM conversations cv
                WHERE cv.id = m.conversation_id
                  AND cv.business_id = :business_id
            )

        ORDER BY
            m.id ASC
    """)


    result = db.execute(
        query,
        {
            "conversation_id": conversation_id,
            "business_id": tenant.business_id,
        },
    ).mappings().all()

    # Return the complete canonical attachment list.  The legacy media_type
    # and media_url columns remain in each row for older clients.
    attachment_by_message: dict[int, list[dict]] = {}
    if result:
        try:
            message_ids = [int(row["message_id"]) for row in result]
            attachment_rows = db.scalars(
                select(MessageAttachment).where(
                    MessageAttachment.business_id == tenant.business_id,
                    MessageAttachment.message_id.in_(message_ids),
                ).order_by(MessageAttachment.id)
            ).all()
            for attachment in attachment_rows:
                attachment_by_message.setdefault(attachment.message_id, []).append({
                    "id": attachment.id,
                    "media_type": attachment.media_type,
                    "mime_type": attachment.mime_type,
                    "file_name": attachment.file_name,
                    "duration_ms": attachment.duration_ms,
                    "external_attachment_id": attachment.external_attachment_id,
                    "media_url": build_media_url(
                        attachment_id=attachment.id,
                        business_id=tenant.business_id,
                    ),
                    "metadata": attachment.metadata_,
                })
        except Exception:
            # Allow a rolling deployment to serve legacy messages before the
            # attachment migration has been applied.
            db.rollback()


    return {
        "conversation_id":
            conversation_id,

        "items": [
            {
                **dict(row),
                "attachments": attachment_by_message.get(int(row["message_id"]), []),
            }
            for row in result
        ],
    }


@router.get("/{conversation_id}/delivery-attempts")
def get_outbound_delivery_attempts(
    conversation_id: int,
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Expose redacted delivery state; never include message bodies or provider data."""
    conversation = db.execute(
        text("SELECT id FROM conversations WHERE id=:conversation_id AND business_id=:business_id LIMIT 1"),
        {"conversation_id": conversation_id, "business_id": tenant.business_id},
    ).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    rows = db.execute(
        text("""
            SELECT client_id, status, error_code, message_id, created_at, updated_at
            FROM channel_outbound_attempts
            WHERE conversation_id=:conversation_id AND business_id=:business_id
            ORDER BY id DESC
            LIMIT :limit
        """),
        {"conversation_id": conversation_id, "business_id": tenant.business_id, "limit": limit},
    ).mappings().all()
    return {"conversation_id": conversation_id, "items": [dict(row) for row in rows]}


# =========================================================
# SEND TEXT
# =========================================================

@router.post(
    "/{conversation_id}/messages",
    dependencies=[Depends(require_write_access)],
)
async def send_message(
    conversation_id: int,
    body: SendMessageRequest,
    db: Session = Depends(
        get_tenant_db
    ),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    text_content = str(body.text or "").strip()
    if not text_content:
        raise HTTPException(status_code=400, detail="Nội dung tin nhắn không được để trống")
    conversation = get_conversation_target(db, conversation_id, tenant.business_id)
    require_responsible_staff(conversation, actor)
    client_id = validate_client_id(body.client_id)
    sent = await send_idempotent_outbound(
        db,
        client_id=client_id,
        channel_id=conversation.get("channel_id"),
        business_id=tenant.business_id,
        conversation_id=conversation_id,
        channel=str(conversation["channel"]),
        recipient_id=str(conversation["external_user_id"]),
        text_content=text_content,
        sender_user_id=actor.id if actor else None,
    )
    return {
        "success": True,
        "status": "sent",
        "channel": conversation["channel"],
        "message_type": "text",
        "conversation_id": conversation_id,
        "external_message_id": sent.get("message_id"),
        "message": sent.get("message"),
        "idempotent_replay": bool((sent.get("meta_response") or {}).get("idempotent_replay")),
    }


def _legacy_send_message(
    conversation_id: int,
    body: SendMessageRequest,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):

    message_text = str(
        body.text
        or ""
    ).strip()


    if not message_text:

        raise HTTPException(
            status_code=400,
            detail=(
                "Nội dung tin nhắn "
                "không được để trống"
            ),
        )


    conversation = (
        get_conversation_target(
            db=db,

            conversation_id=
                conversation_id,
            business_id=tenant.business_id,
        )
    )
    require_responsible_staff(conversation, actor)


    channel = conversation[
        "channel"
    ]

    recipient_id = str(
        conversation[
            "external_user_id"
        ]
    )

    logger.info("Outbound channel send started: channel=%s operation=text", channel)


    # =====================================================
    # FACEBOOK TEXT
    # =====================================================

    if channel == "facebook":

        try:

            result = (
                send_facebook_message(
                    recipient_id=
                        recipient_id,

                    text=
                        message_text,
                    db=db,
                    business_id=tenant.business_id,
                )
            )


            external_message_id = (
                result.get(
                    "message_id"
                )
            )


            save_outbound_message(
                db=db,

                conversation_id=
                    conversation_id,

                channel=
                    "facebook",

                recipient_id=
                    recipient_id,

                external_message_id=
                    external_message_id,

                content=
                    message_text,

                media_type=
                    None,

                media_url=
                    None,

                meta_response=
                    result,
            )


            print(
                "✅ OUTBOUND FACEBOOK "
                "TEXT SAVED"
            )

            logger.info("Outbound channel message saved: provider=facebook")

            return {
                "success":
                    True,

                "status":
                    "sent",

                "channel":
                    "facebook",

                "message_type":
                    "text",

                "conversation_id":
                    conversation_id,

                "external_message_id":
                    external_message_id,
            }


        except MetaAPIError as exc:

            db.rollback()

            _log_meta_error(exc)

            raise HTTPException(
                status_code=meta_error_status_code(
                    exc
                ),
                detail=exc.to_detail(),
            )

        except Exception as exc:

            db.rollback()

            logger.error("Outbound channel send failed: provider=facebook operation=text error_type=%s", type(exc).__name__)

            raise HTTPException(
                status_code=500,

                detail=(
                    "Không thể gửi "
                    "Facebook message"
                ),
            )


    # =====================================================
    # INSTAGRAM TEXT
    # =====================================================

    if channel == "instagram":

        try:

            log_instagram_recipient_audit(
                db=db,
                conversation_id=conversation_id,
                db_external_user_id=recipient_id,
            )

            result = (
                send_instagram_message(
                    recipient_id=
                        recipient_id,

                    text=
                        message_text,
                    db=db,
                    business_id=tenant.business_id,
                )
            )


            external_message_id = (
                result.get(
                    "message_id"
                )
            )


            save_outbound_message(
                db=db,

                conversation_id=
                    conversation_id,

                channel=
                    "instagram",

                recipient_id=
                    recipient_id,

                external_message_id=
                    external_message_id,

                content=
                    message_text,

                media_type=
                    None,

                media_url=
                    None,

                meta_response=
                    result,
            )


            print(
                "✅ OUTBOUND INSTAGRAM "
                "TEXT SAVED"
            )

            logger.info("Outbound channel message saved: provider=instagram")

            return {
                "success":
                    True,

                "status":
                    "sent",

                "channel":
                    "instagram",

                "message_type":
                    "text",

                "conversation_id":
                    conversation_id,

                "external_message_id":
                    external_message_id,
            }


        except MetaAPIError as exc:

            db.rollback()

            _log_meta_error(exc)

            raise HTTPException(
                status_code=meta_error_status_code(
                    exc
                ),
                detail=exc.to_detail(),
            )

        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        except Exception as exc:

            db.rollback()

            logger.error("Outbound channel send failed: provider=instagram operation=text error_type=%s", type(exc).__name__)

            raise HTTPException(
                status_code=500,

                detail=(
                    "Không thể gửi "
                    "Instagram message"
                ),
            )


    # =====================================================
    # TELEGRAM TEXT
    # =====================================================

    if channel == "telegram":

        try:
            result, telegram_channel = send_telegram_text(
                db=db,
                conversation=conversation,
                recipient_id=recipient_id,
                text_content=message_text,
                business_id=tenant.business_id,
            )
            external_message_id = telegram_external_message_id(result, telegram_channel)
            saved_message = save_outbound_message(
                db=db,
                conversation_id=conversation_id,
                channel="telegram",
                recipient_id=recipient_id,
                external_message_id=external_message_id,
                content=message_text,
                media_type=None,
                media_url=None,
                meta_response=result,
            )
            return {
                "success": True,
                "status": "sent",
                "channel": "telegram",
                "message_type": "text",
                "conversation_id": conversation_id,
                "external_message_id": external_message_id,
                "message": saved_message,
            }
        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            logger.error("Outbound channel send failed: provider=telegram operation=text error_type=%s", type(exc).__name__)
            raise HTTPException(
                status_code=502,
                detail="Không thể gửi Telegram message",
            ) from exc


    # =====================================================
    # TIKTOK BRIDGE TEXT
    # =====================================================

    if channel == "tiktok":
        try:
            result, _ = send_tiktok_text(
                db=db,
                conversation=conversation,
                recipient_id=recipient_id,
                text_content=message_text,
                business_id=tenant.business_id,
            )
            external_message_id = result.get("message_id")
            saved_message = save_outbound_message(
                db=db,
                conversation_id=conversation_id,
                channel="tiktok",
                recipient_id=recipient_id,
                external_message_id=external_message_id,
                content=message_text,
                media_type=None,
                media_url=None,
                meta_response=result,
            )
            return {
                "success": True,
                "status": "sent",
                "channel": "tiktok",
                "message_type": "text",
                "conversation_id": conversation_id,
                "external_message_id": external_message_id,
                "message": saved_message,
            }
        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            logger.error("Outbound channel send failed: provider=tiktok operation=text error_type=%s", type(exc).__name__)
            raise HTTPException(
                status_code=502,
                detail="Không thể gửi TikTok message",
            ) from exc


    raise HTTPException(
        status_code=400,

        detail=(
            "Send message chưa hỗ trợ "
            f"channel: {channel}"
        ),
    )


# =========================================================
# UNIFIED SEND
# =========================================================

@router.post(
    "/{conversation_id}/send",
    dependencies=[Depends(require_write_access)],
)
async def unified_send(
    conversation_id: int,
    text_value: str | None = Form(
        None,
        alias="text",
    ),
    client_id: str | None = Form(
        None,
    ),
    media_client_id: str | None = Form(None),
    text_client_id: str | None = Form(None),
    file: UploadFile | None = File(
        None
    ),
    db: Session = Depends(
        get_tenant_db
    ),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    message_text = str(
        text_value
        or ""
    ).strip()

    has_file = (
        file is not None
        and bool(
            file.filename
        )
    )

    if (
        not message_text
        and not has_file
    ):
        raise HTTPException(
            status_code=400,
            detail="Text hoac file la bat buoc",
        )

    conversation = get_conversation_target(
        db=db,
        conversation_id=conversation_id,
        business_id=tenant.business_id,
    )
    require_responsible_staff(conversation, actor)

    media_key = None
    text_key = None
    if has_file:
        media_key = validate_client_id(media_client_id or client_id)
        if message_text:
            text_key = validate_client_id(text_client_id or (f"{client_id}-text" if client_id else None))
    else:
        text_key = validate_client_id(text_client_id or client_id)

    channel = conversation[
        "channel"
    ]

    recipient_id = str(
        conversation[
            "external_user_id"
        ]
    )

    logger.info("Outbound channel send started: channel=%s operation=compose", channel)

    results: list[dict] = []
    media_url = None
    media_path = None

    try:
        if has_file and file is not None:
            media_url, media_path = await prepare_uploaded_image(
                file=file,
                conversation_id=conversation_id,
            )

            sent_media = await send_idempotent_outbound(
                db=db,
                client_id=media_key,
                channel_id=conversation.get("channel_id"),
                business_id=tenant.business_id,
                conversation_id=conversation_id,
                channel=channel,
                recipient_id=recipient_id,
                image_url=media_url,
                sender_user_id=actor.id if actor else None,
            )
            if (sent_media.get("meta_response") or {}).get("idempotent_replay"):
                media_path.unlink(missing_ok=True)
            results.append(sent_media)

        if message_text:
            results.append(
                await send_idempotent_outbound(
                    db=db,
                    client_id=text_key,
                    channel_id=conversation.get("channel_id"),
                    business_id=tenant.business_id,
                    conversation_id=conversation_id,
                    channel=channel,
                    recipient_id=recipient_id,
                    text_content=message_text,
                    sender_user_id=actor.id if actor else None,
                )
            )

    except MetaAPIError as exc:
        db.rollback()
        _log_meta_error(exc)
        raise HTTPException(
            status_code=meta_error_status_code(
                exc
            ),
            detail=exc.to_detail(),
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    print(
        "[UI MEDIA ROUTE END] "
        f"conversation_id={conversation_id} | "
        f"messages={len(results)} | "
        "success=True"
    )

    return {
        "success":
            True,
        "client_id":
            client_id or media_key or text_key,
        "conversation_id":
            conversation_id,
        "media_type":
            "image"
            if media_url
            else None,
        "media_url":
            media_url,
        "messages": [
            item.get(
                "message"
            )
            for item in results
            if item.get(
                "message"
            )
        ],
        "message_ids": [
            item.get(
                "message_id"
            )
            for item in results
        ],
    }


# =========================================================
# SEND IMAGE BY URL
# =========================================================

@router.post("/{conversation_id}/send-media", dependencies=[Depends(require_write_access)])
async def send_media_message(
    conversation_id: int,
    body: SendMediaRequest,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    """Send one canonical media attachment through the linked channel."""
    media_type = str(body.media_type or "").strip().lower()
    try:
        MediaType(media_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"media_type không hợp lệ: {media_type}") from exc
    if media_type == "text":
        raise HTTPException(status_code=422, detail="send-media chỉ nhận image/audio/sticker/video/file")
    media_url = str(body.media_url or "").strip()
    if not media_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="media_url phải là URL http/https")
    if media_type == "image":
        check_public_image_url(media_url)
    conversation = get_conversation_target(
        db=db,
        conversation_id=conversation_id,
        business_id=tenant.business_id,
    )
    require_responsible_staff(conversation, actor)
    client_id = validate_client_id(body.client_id)
    channel = str(conversation["channel"] or "").strip().lower()
    recipient_id = str(conversation["external_user_id"])
    attempt_id, replay = _claim_outbound_delivery(
        db,
        client_id=client_id,
        channel_id=conversation.get("channel_id"),
        business_id=tenant.business_id,
        conversation_id=conversation_id,
    )
    if replay:
        return {
            "success": True,
            "status": "sent",
            "channel": channel,
            "message_type": media_type,
            "conversation_id": conversation_id,
            "external_message_id": replay.get("external_message_id"),
            "message": replay,
            "idempotent_replay": True,
        }

    try:
        if channel == "facebook":
            result = await run_in_threadpool(
                send_facebook_media,
                recipient_id=recipient_id,
                media_type=media_type,
                media_url=media_url,
                caption=body.caption,
                db=db,
                business_id=tenant.business_id,
            )
        elif channel == "instagram":
            result = await run_in_threadpool(
                send_instagram_media,
                recipient_id=recipient_id,
                media_type=media_type,
                media_url=media_url,
                caption=body.caption,
                db=db,
                business_id=tenant.business_id,
            )
        elif channel == "telegram":
            result = await run_in_threadpool(
                send_telegram_media,
                db=db,
                business_id=tenant.business_id,
                conversation_id=conversation_id,
                recipient_id=recipient_id,
                media_type=media_type,
                media_url=media_url,
                caption=body.caption,
            )
        elif channel == "zalo":
            result = await run_in_threadpool(
                send_zalo_media,
                db=db,
                business_id=tenant.business_id,
                conversation_id=conversation_id,
                recipient_id=recipient_id,
                media_type=media_type,
                media_url=media_url,
                caption=body.caption,
            )
        else:
            raise HTTPException(status_code=422, detail=f"Kênh {channel} chưa hỗ trợ gửi media")
    except Exception as exc:
        db.rollback()
        mark_outbound_attempt_failed(db, attempt_id, exc)
        if isinstance(exc, HTTPException):
            raise
        if isinstance(exc, (ValueError, LookupError)):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if isinstance(exc, MetaAPIError):
            raise HTTPException(status_code=meta_error_status_code(exc), detail=exc.to_detail()) from exc
        raise HTTPException(status_code=502, detail=f"Không thể gửi media qua {channel}") from exc

    external_message_id = result.get("message_id") or (result.get("result") or {}).get("message_id")
    saved = save_outbound_message(
        db=db,
        conversation_id=conversation_id,
        channel=channel,
        recipient_id=recipient_id,
        external_message_id=external_message_id,
        content=body.caption,
        media_type=media_type,
        media_url=media_url,
        meta_response=result,
        sender_type="staff",
        sender_user_id=actor.id if actor else None,
    )
    if not saved:
        mark_outbound_attempt_failed(
            db, attempt_id, HTTPException(status_code=502, detail="Outbound message was not persisted")
        )
        raise HTTPException(status_code=502, detail="Không xác nhận được trạng thái lưu tin nhắn; vui lòng kiểm tra kênh trước khi gửi lại.")
    mark_outbound_attempt_sent(db, attempt_id, message_id=saved.get("message_id"))
    if saved and conversation.get("channel_id"):
        try:
            from app.services.media_service import save_message_attachments

            attachment = NormalizedAttachment(
                media_type=MediaType(media_type),
                url=media_url,
                metadata={
                    "caption": body.caption,
                    "provider_message_id": external_message_id,
                },
            )
            save_message_attachments(
                db,
                message_id=int(saved["message_id"]),
                business_id=tenant.business_id,
                channel_id=int(conversation["channel_id"]),
                attachments=[attachment],
            )
            db.commit()
        except Exception:
            db.rollback()
    await broadcast_message_created(saved, business_id=tenant.business_id)
    return {
        "success": True,
        "status": "sent",
        "channel": channel,
        "message_type": media_type,
        "conversation_id": conversation_id,
        "external_message_id": external_message_id,
        "message": saved,
        "provider_response": result,
    }

@router.post(
    "/{conversation_id}/media",
    dependencies=[Depends(require_write_access)],
)
async def send_media(
    conversation_id: int,
    body: SendMediaRequest,
    db: Session = Depends(
        get_tenant_db
    ),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    if str(body.media_type or "image").strip().lower() != "image":
        raise HTTPException(status_code=422, detail="/media chỉ nhận image; dùng /send-media cho media khác")
    return await send_media_message(conversation_id, body, db, tenant, actor)


def _legacy_send_media(
    conversation_id: int,
    body: SendMediaRequest,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):

    media_type = str(
        body.media_type
        or "image"
    ).strip().lower()


    if media_type != "image":

        raise HTTPException(
            status_code=400,

            detail=(
                "Hiện tại chỉ hỗ trợ "
                "gửi image"
            ),
        )


    media_url = str(
        body.media_url
        or ""
    ).strip()


    if not media_url:

        raise HTTPException(
            status_code=400,

            detail=(
                "media_url "
                "không được để trống"
            ),
        )


    if not (
        media_url.startswith(
            "http://"
        )
        or media_url.startswith(
            "https://"
        )
    ):

        raise HTTPException(
            status_code=400,

            detail=(
                "media_url phải là "
                "URL http/https"
            ),
        )

    check_public_image_url(
        media_url
    )


    conversation = (
        get_conversation_target(
            db=db,

            conversation_id=
                conversation_id,
            business_id=tenant.business_id,
        )
    )
    require_responsible_staff(conversation, actor)


    channel = conversation[
        "channel"
    ]

    recipient_id = str(
        conversation[
            "external_user_id"
        ]
    )

    logger.info("Outbound channel send started: channel=%s operation=image", channel)


    # =====================================================
    # FACEBOOK IMAGE
    # =====================================================

    if channel == "facebook":

        try:

            logger.debug("Outbound media provider request started: provider=facebook media_type=image")

            result = (
                send_facebook_image(
                    recipient_id=
                        recipient_id,

                    image_url=
                        media_url,
                    db=db,
                    business_id=tenant.business_id,
                )
            )


            external_message_id = (
                result.get(
                    "message_id"
                )
            )


            save_outbound_message(
                db=db,

                conversation_id=
                    conversation_id,

                channel=
                    "facebook",

                recipient_id=
                    recipient_id,

                external_message_id=
                    external_message_id,

                content=
                    None,

                media_type=
                    "image",

                media_url=
                    media_url,

                meta_response=
                    result,
            )


            print(
                "✅ OUTBOUND FACEBOOK "
                "IMAGE SAVED"
            )


            logger.info("Outbound media message saved: provider=facebook")

            return {
                "success":
                    True,

                "status":
                    "sent",

                "channel":
                    "facebook",

                "message_type":
                    "image",

                "media_url":
                    media_url,

                "external_message_id":
                    external_message_id,

                "message_id":
                    external_message_id,
            }


        except MetaAPIError as exc:

            db.rollback()

            _log_meta_error(exc)

            raise HTTPException(
                status_code=meta_error_status_code(
                    exc
                ),
                detail=exc.to_detail(),
            )


        except Exception as exc:

            db.rollback()

            logger.error("Outbound channel send failed: provider=facebook operation=image error_type=%s", type(exc).__name__)

            raise HTTPException(
                status_code=500,

                detail=(
                    "Không thể gửi "
                    "Facebook image"
                ),
            )


    # =====================================================
    # INSTAGRAM IMAGE
    # =====================================================

    if channel == "instagram":

        try:

            log_instagram_recipient_audit(
                db=db,
                conversation_id=conversation_id,
                db_external_user_id=recipient_id,
            )

            result = (
                send_instagram_image(
                    recipient_id=
                        recipient_id,

                    image_url=
                        media_url,
                    db=db,
                    business_id=tenant.business_id,
                )
            )


            external_message_id = (
                result.get(
                    "message_id"
                )
            )


            save_outbound_message(
                db=db,

                conversation_id=
                    conversation_id,

                channel=
                    "instagram",

                recipient_id=
                    recipient_id,

                external_message_id=
                    external_message_id,

                content=
                    None,

                media_type=
                    "image",

                media_url=
                    media_url,

                meta_response=
                    result,
            )


            print(
                "✅ OUTBOUND INSTAGRAM "
                "IMAGE SAVED"
            )


            return {
                "success":
                    True,

                "status":
                    "sent",

                "channel":
                    "instagram",

                "message_type":
                    "image",

                "media_url":
                    media_url,

                "external_message_id":
                    external_message_id,

                "message_id":
                    external_message_id,
            }


        except MetaAPIError as exc:

            db.rollback()

            _log_meta_error(exc)

            raise HTTPException(
                status_code=meta_error_status_code(
                    exc
                ),
                detail=exc.to_detail(),
            )

        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        except Exception as exc:

            db.rollback()

            logger.error("Outbound channel send failed: provider=instagram operation=image error_type=%s", type(exc).__name__)

            raise HTTPException(
                status_code=500,

                detail=(
                    "Không thể gửi "
                    "Instagram image"
                ),
            )


    raise HTTPException(
        status_code=400,

        detail=(
            "Send media chưa hỗ trợ "
            f"channel: {channel}"
        ),
    )


# =========================================================
# SERVE UPLOADED IMAGE
# =========================================================

@router.get(
    "/uploads/{filename}"
)
def get_uploaded_image(
    filename: str,
):
    """
    Cho Meta tải ảnh đã upload.
    """

    safe_filename = Path(
        filename
    ).name

    file_path = (
        UPLOAD_DIR
        / safe_filename
    )


    if (
        not file_path.exists()
        or not file_path.is_file()
    ):

        raise HTTPException(
            status_code=404,
            detail="Image not found",
        )

    media_type = (
        get_upload_file_media_type(
            file_path
        )
    )

    return FileResponse(
        path=file_path,
        media_type=media_type,
    )


@router.get("/media-uploads/{filename}")
def get_uploaded_media(filename: str):
    """Serve a composer upload to a channel provider using a safe filename."""
    safe_filename = Path(filename).name
    file_path = UPLOAD_DIR / safe_filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Media not found")
    media_type = mimetypes.guess_type(safe_filename)[0] or "application/octet-stream"
    return FileResponse(path=file_path, media_type=media_type)


# =========================================================
# UPLOAD + SEND IMAGE
# =========================================================

@router.post(
    "/{conversation_id}/media/upload",
    dependencies=[Depends(require_write_access)],
)
async def upload_and_send_image(
    conversation_id: int,
    file: UploadFile = File(...),
    client_id: str = Form(...),
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    conversation = get_conversation_target(db, conversation_id, tenant.business_id)
    require_responsible_staff(conversation, actor)
    media_url, file_path = await prepare_uploaded_image(file, conversation_id)
    try:
        result = await send_media_message(
            conversation_id,
            SendMediaRequest(media_type="image", media_url=media_url, client_id=client_id),
            db,
            tenant,
            actor,
        )
        if result.get("idempotent_replay"):
            file_path.unlink(missing_ok=True)
        return result
    except Exception:
        file_path.unlink(missing_ok=True)
        raise


async def _legacy_upload_and_send_image(
    conversation_id: int,

    file: UploadFile = File(
        ...
    ),

    db: Session = Depends(
        get_tenant_db
    ),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    """
    Flow:

    File từ máy
        ↓
    FastAPI lưu uploads/
        ↓
    tạo URL public
        ↓
    gửi URL sang Meta
        ↓
    Facebook / Instagram nhận ảnh
    """

    conversation = get_conversation_target(
        db=db,
        conversation_id=conversation_id,
        business_id=tenant.business_id,
    )
    require_responsible_staff(conversation, actor)

    logger.info("Outbound channel image upload started: business_id=%s", tenant.business_id)


    # =====================================================
    # CHECK CONTENT TYPE
    # =====================================================

    upload_content_type = (
        file.content_type
        or ""
    ).lower()


    if (
        upload_content_type
        not in ALLOWED_IMAGE_TYPES
    ):

        raise HTTPException(
            status_code=400,

            detail=(
                "Chỉ hỗ trợ ảnh "
                "JPG, JPEG hoặc PNG"
            ),
        )


    # =====================================================
    # READ FILE
    # =====================================================

    file_bytes = (
        await file.read()
    )


    if not file_bytes:

        raise HTTPException(
            status_code=400,
            detail="File ảnh bị rỗng",
        )


    if (
        len(file_bytes)
        > MAX_IMAGE_SIZE
    ):

        raise HTTPException(
            status_code=400,

            detail=(
                "Ảnh quá lớn. "
                "Tối đa 8MB"
            ),
        )

    logger.info("Inbound image upload received: content_type=%s size_bytes=%s", upload_content_type, len(file_bytes))


    # =====================================================
    # VERIFY REAL IMAGE TYPE
    # =====================================================

    original_content_type, _ = (
        detect_image_type(
            file_bytes
        )
    )

    if original_content_type != upload_content_type:
        raise HTTPException(
            status_code=400,
            detail={
                "stage":
                    "image_validation",
                "message":
                    "Content-Type không khớp binary ảnh thật",
                "upload_content_type":
                    upload_content_type,
                "detected_content_type":
                    original_content_type,
            },
        )


    # =====================================================
    # NORMALIZE IMAGE
    # =====================================================

    normalized_bytes, normalize_info = (
        normalize_image_to_jpeg(
            file_bytes
        )
    )

    content_type = "image/jpeg"
    extension = ".jpg"

    filename = (
        f"{uuid.uuid4().hex}"
        f"{extension}"
    )


    file_path = (
        UPLOAD_DIR
        / filename
    )


    # =====================================================
    # SAVE FILE
    # =====================================================

    try:

        with open(
            file_path,
            "wb",
        ) as output_file:

            output_file.write(
                normalized_bytes
            )


    except Exception as exc:
        logger.error("Media upload persistence failed: error_type=%s", type(exc).__name__)

        raise HTTPException(
            status_code=500,

            detail=(
                "Không thể lưu "
                "file upload"
            ),
        )


    # =====================================================
    # PUBLIC URL
    # =====================================================

    public_base_url = (
        get_public_base_url()
    )


    media_url = (
        f"{public_base_url}"
        f"/api/conversations"
        f"/uploads/{filename}"
    )


    logger.info("Media upload normalized: format=%s size_bytes=%s", normalize_info["original_format"], len(normalized_bytes))

    await check_public_image_url_async(
        media_url
    )


    # =====================================================
    # GET CONVERSATION
    # =====================================================

    conversation = (
        get_conversation_target(
            db=db,

            conversation_id=
                conversation_id,
            business_id=tenant.business_id,
        )
    )


    channel = (
        conversation[
            "channel"
        ]
    )


    recipient_id = str(
        conversation[
            "external_user_id"
        ]
    )

    logger.info("Outbound channel send started: channel=%s operation=uploaded_image", channel)


    # =====================================================
    # FACEBOOK
    # =====================================================

    if channel == "facebook":

        try:

            logger.debug("Outbound media provider request started: provider=facebook media_type=image")

            result = await run_in_threadpool(
                send_facebook_image,
                recipient_id=recipient_id,
                image_url=media_url,
            )


            external_message_id = (
                result.get(
                    "message_id"
                )
            )


            save_outbound_message(
                db=db,

                conversation_id=
                    conversation_id,

                channel=
                    "facebook",

                recipient_id=
                    recipient_id,

                external_message_id=
                    external_message_id,

                content=
                    None,

                media_type=
                    "image",

                media_url=
                    media_url,

                meta_response=
                    result,
            )


            print(
                "✅ FACEBOOK IMAGE "
                "UPLOAD + SEND SUCCESS"
            )


            return {
                "success":
                    True,

                "status":
                    "sent",

                "channel":
                    "facebook",

                "message_type":
                    "image",

                "conversation_id":
                    conversation_id,

                "media_url":
                    media_url,

                "external_message_id":
                    external_message_id,

                "message_id":
                    external_message_id,
            }


        except MetaAPIError as exc:

            db.rollback()

            _log_meta_error(exc)


            try:

                file_path.unlink(
                    missing_ok=True
                )

            except Exception:
                pass


            raise HTTPException(
                status_code=meta_error_status_code(
                    exc
                ),
                detail=exc.to_detail(),
            )


        except Exception as exc:

            db.rollback()

            logger.error("Outbound channel send failed: provider=facebook operation=uploaded_image error_type=%s", type(exc).__name__)


            try:

                file_path.unlink(
                    missing_ok=True
                )

            except Exception:
                pass


            raise HTTPException(
                status_code=500,

                detail=(
                    "Không thể gửi "
                    "ảnh Facebook"
                ),
            )


    # =====================================================
    # INSTAGRAM
    # =====================================================

    if channel == "instagram":

        try:

            logger.debug("Outbound media provider request started: provider=instagram media_type=image")

            result = await run_in_threadpool(
                send_instagram_image,
                recipient_id=recipient_id,
                image_url=media_url,
                db=db,
                business_id=tenant.business_id,
            )


            external_message_id = (
                result.get(
                    "message_id"
                )
            )


            save_outbound_message(
                db=db,

                conversation_id=
                    conversation_id,

                channel=
                    "instagram",

                recipient_id=
                    recipient_id,

                external_message_id=
                    external_message_id,

                content=
                    None,

                media_type=
                    "image",

                media_url=
                    media_url,

                meta_response=
                    result,
            )


            print(
                "✅ INSTAGRAM IMAGE "
                "UPLOAD + SEND SUCCESS"
            )


            return {
                "success":
                    True,

                "status":
                    "sent",

                "channel":
                    "instagram",

                "message_type":
                    "image",

                "conversation_id":
                    conversation_id,

                "media_url":
                    media_url,

                "external_message_id":
                    external_message_id,

                "message_id":
                    external_message_id,
            }


        except MetaAPIError as exc:

            db.rollback()

            _log_meta_error(exc)


            try:

                file_path.unlink(
                    missing_ok=True
                )

            except Exception:
                pass


            raise HTTPException(
                status_code=meta_error_status_code(
                    exc
                ),
                detail=exc.to_detail(),
            )


        except Exception as exc:

            db.rollback()

            logger.error("Outbound channel send failed: provider=instagram operation=uploaded_image error_type=%s", type(exc).__name__)


            try:

                file_path.unlink(
                    missing_ok=True
                )

            except Exception:
                pass


            raise HTTPException(
                status_code=500,

                detail=(
                    "Không thể gửi "
                    "ảnh Instagram"
                ),
            )


    # =====================================================
    # UNSUPPORTED CHANNEL
    # =====================================================

    try:

        file_path.unlink(
            missing_ok=True
        )

    except Exception:
        pass


    raise HTTPException(
        status_code=400,

        detail=(
            "Upload ảnh chưa hỗ trợ "
            f"channel: {channel}"
        ),
    )


@router.post("/{conversation_id}/media/upload-generic", dependencies=[Depends(require_write_access)])
async def upload_and_send_generic_media(
    conversation_id: int,
    file: UploadFile = File(...),
    client_id: str = Form(...),
    media_type: str = Form("file"),
    caption: str | None = Form(None),
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    """Upload and send audio/video/sticker/file (and non-normalized images).

    The existing ``media/upload`` endpoint deliberately normalizes images for
    Meta.  This endpoint preserves the original bytes for media where provider
    metadata (audio codec, sticker format, video container) matters, then
    delegates delivery and persistence to the canonical ``send-media`` route.
    """
    conversation = get_conversation_target(
        db=db,
        conversation_id=conversation_id,
        business_id=tenant.business_id,
    )
    require_responsible_staff(conversation, actor)

    normalized_type = str(media_type or "").strip().lower()
    try:
        MediaType(normalized_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"media_type không hợp lệ: {normalized_type}") from exc
    if normalized_type in {"text", "unknown"}:
        raise HTTPException(status_code=422, detail="upload-generic chỉ nhận image/audio/sticker/video/file")

    content_type = str(file.content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    allowed_types = ALLOWED_MEDIA_UPLOAD_TYPES[normalized_type]
    if content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Content-Type không phù hợp với media_type={normalized_type}",
                "content_type": content_type,
                "allowed": sorted(allowed_types),
            },
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="File upload bị rỗng")
    if len(file_bytes) > MAX_MEDIA_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="File media quá lớn. Tối đa 25MB")

    suffix = Path(file.filename or "").suffix.lower()
    if not suffix or len(suffix) > 10 or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789." for char in suffix):
        suffix = mimetypes.guess_extension(content_type) or ".bin"
    filename = f"{uuid.uuid4().hex}{suffix}"
    file_path = UPLOAD_DIR / filename
    try:
        file_path.write_bytes(file_bytes)
        upload_path = file_path
        upload_content_type = content_type
        if normalized_type == "audio":
            channel = str(conversation["channel"] or "").strip().lower()
            if channel == "zalo":
                upload_path, upload_content_type = normalize_zalo_audio_upload(
                    file_path,
                    content_type=content_type,
                )
        media_url = f"{get_public_base_url()}/api/conversations/media-uploads/{upload_path.name}"
        result = await send_media_message(
            conversation_id,
            SendMediaRequest(media_type=normalized_type, media_url=media_url, caption=caption, client_id=client_id),
            db,
            tenant,
            actor,
        )
        if result.get("idempotent_replay"):
            file_path.unlink(missing_ok=True)
            if upload_path != file_path:
                upload_path.unlink(missing_ok=True)
            return result
        result["upload"] = {
            "filename": file.filename,
            "content_type": upload_content_type,
            "size": upload_path.stat().st_size,
            "media_url": media_url,
        }
        return result
    except RuntimeError as exc:
        db.rollback()
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        db.rollback()
        file_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        db.rollback()
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Không thể upload và gửi media") from exc


# =========================================================
# AUTO-REPLY SETTINGS ENDPOINTS
# =========================================================

class AutoReplyStatusRequest(BaseModel):
    auto_reply_enabled: bool


@router.get("/auto-reply-status")
async def get_auto_reply_status(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    from app.services.auto_reply_service import get_auto_reply_enabled
    return {"auto_reply_enabled": get_auto_reply_enabled(db, tenant.business_id)}


@router.post("/auto-reply-status", dependencies=[Depends(require_write_access)])
async def set_auto_reply_status(
    req: AutoReplyStatusRequest,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    from app.services.auto_reply_service import set_auto_reply_enabled
    enabled = set_auto_reply_enabled(db, req.auto_reply_enabled, tenant.business_id)
    return {"auto_reply_enabled": enabled}
