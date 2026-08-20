import json
import uuid

from io import BytesIO
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)

from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool

from pydantic import BaseModel

from sqlalchemy import text
from sqlalchemy.orm import Session

import httpx
from PIL import Image

from app.core.config import settings
from app.db.dependencies import get_db
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


router = APIRouter()


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


class SendMediaRequest(
    BaseModel
):
    media_url: str
    media_type: str = "image"


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

    return base_url.rstrip(
        "/"
    )


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
        print(
            "[PUBLIC URL CHECK] "
            f"request_error={exc}"
        )
        raise HTTPException(
            status_code=400,
            detail={
                "stage":
                    "public_url_check",
                "message":
                    str(exc),
                "image_url":
                    image_url,
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

    print(
        "[PUBLIC URL CHECK] "
        f"status={response.status_code} | "
        f"content_type={content_type} | "
        f"content_length={content_length} | "
        f"final_url={response.url}"
    )

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
        print(
            "[PUBLIC URL CHECK] "
            f"request_error={exc}"
        )
        raise HTTPException(
            status_code=400,
            detail={
                "stage":
                    "public_url_check",
                "message":
                    str(exc),
                "image_url":
                    image_url,
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

    print(
        "[PUBLIC URL CHECK] "
        f"status={response.status_code} | "
        f"content_type={content_type} | "
        f"content_length={content_length} | "
        f"final_url={response.url}"
    )

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

    print(
        "[UI FILE RECEIVED] "
        f"filename={file.filename!r} | "
        f"content_type={upload_content_type!r} | "
        f"size={len(file_bytes)}"
    )

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
        print(
            "SAVE UPLOAD ERROR:",
            str(exc),
        )
        raise HTTPException(
            status_code=500,
            detail="Khong the luu file upload",
        )

    media_url = (
        f"{get_public_base_url()}"
        f"/api/conversations"
        f"/uploads/{filename}"
    )

    print(
        "[IMAGE NORMALIZE] "
        f"original_format={normalize_info['original_format']} | "
        f"original_mode={normalize_info['original_mode']} | "
        f"original_size={normalize_info['original_size']} | "
        "normalized_format=JPEG | "
        "normalized_mode=RGB | "
        f"normalized_path={file_path} | "
        f"normalized_size={len(normalized_bytes)}"
    )

    print(
        "[IMAGE UPLOAD] "
        f"conversation_id={conversation_id} | "
        f"filename={filename} | "
        "content_type=image/jpeg | "
        f"size={len(normalized_bytes)} | "
        f"saved_path={file_path} | "
        f"public_url={media_url}"
    )

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

    print(
        "[RECIPIENT AUDIT] "
        f"db_external_user_id={db_external_user_id!r} | "
        f"webhook_sender_id={webhook_sender_id!r} | "
        f"graph_from_id={graph_from_id!r} | "
        f"conversation_participant_id={selected_recipient_id!r} | "
        f"selected_recipient_id={selected_recipient_id!r} | "
        "recipient_id_type='IGSID_FROM_PAGE_CONVERSATIONS_API'"
    )


# =========================================================
# HELPER - GET CONVERSATION
# =========================================================

def get_conversation_target(
    db: Session,
    conversation_id: int,
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
                cv.customer_id,
                c.external_user_id

            FROM conversations cv

            JOIN customers c
                ON c.id = cv.customer_id

            WHERE
                cv.id = :conversation_id

            LIMIT 1
        """),
        {
            "conversation_id":
                conversation_id,
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

    db.commit()

    row = result.mappings().first()

    if row:
        return dict(
            row
        )

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
        return dict(
            existing
        )

    return None


async def broadcast_message_created(
    message: dict | None,
):
    if not message:
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
        }
    )


async def send_and_save_outbound(
    db: Session,
    conversation_id: int,
    channel: str,
    recipient_id: str,
    text_content: str | None = None,
    image_url: str | None = None,
) -> dict:
    if image_url:
        print(
            "[UI CALL SERVICE] "
            f"service=send_{channel}_image | "
            f"recipient_id={recipient_id} | "
            f"media_url={image_url}"
        )

        if channel == "facebook":
            result = await run_in_threadpool(
                send_facebook_image,
                recipient_id=recipient_id,
                image_url=image_url,
            )
        elif channel == "instagram":
            result = await run_in_threadpool(
                send_instagram_image,
                recipient_id=recipient_id,
                image_url=image_url,
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
        )

    else:
        print(
            "[UI CALL SERVICE] "
            f"service=send_{channel}_message | "
            f"recipient_id={recipient_id}"
        )

        if channel == "facebook":
            result = await run_in_threadpool(
                send_facebook_message,
                recipient_id=recipient_id,
                text=text_content or "",
            )
        elif channel == "instagram":
            result = await run_in_threadpool(
                send_instagram_message,
                recipient_id=recipient_id,
                text=text_content or "",
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
            content=text_content,
            media_type=None,
            media_url=None,
            meta_response=result,
        )

    print(
        "[UI SERVICE RESULT] "
        "status=success | "
        f"message_id={external_message_id}"
    )

    await broadcast_message_created(
        saved_message
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
    db: Session = Depends(
        get_db
    ),
):

    query = text("""
        SELECT
            cv.id AS conversation_id,
            cv.customer_id,

            c.external_user_id,
            c.name AS customer_name,
            c.avatar_url,

            cv.channel,
            cv.status,
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
            ) AS last_message_at

        FROM conversations cv

        JOIN customers c
            ON c.id = cv.customer_id

        ORDER BY
            last_message_at DESC
            NULLS LAST
    """)


    result = db.execute(
        query
    ).mappings().all()


    return {
        "items": [
            dict(row)
            for row in result
        ]
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
        get_db
    ),
):

    conversation = db.execute(
        text("""
            SELECT id

            FROM conversations

            WHERE
                id = :conversation_id

            LIMIT 1
        """),
        {
            "conversation_id":
                conversation_id,
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

        ORDER BY
            m.id ASC
    """)


    result = db.execute(
        query,
        {
            "conversation_id":
                conversation_id,
        },
    ).mappings().all()


    return {
        "conversation_id":
            conversation_id,

        "items": [
            dict(row)
            for row in result
        ],
    }


# =========================================================
# SEND TEXT
# =========================================================

@router.post(
    "/{conversation_id}/messages"
)
def send_message(
    conversation_id: int,
    body: SendMessageRequest,
    db: Session = Depends(
        get_db
    ),
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
        )
    )


    channel = conversation[
        "channel"
    ]

    recipient_id = str(
        conversation[
            "external_user_id"
        ]
    )

    print(
        "[UI MEDIA ROUTE START] "
        f"conversation_id={conversation_id} | "
        f"channel={channel} | "
        f"recipient_id={recipient_id}"
    )


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

            print(
                "[UI SERVICE RESULT] "
                "status=success | "
                f"message_id={external_message_id}"
            )

            print(
                "[UI MEDIA ROUTE END] "
                f"conversation_id={conversation_id} | "
                "success=True"
            )

            print(
                "[UI SERVICE RESULT] "
                "status=success | "
                f"message_id={external_message_id}"
            )

            print(
                "[UI MEDIA ROUTE END] "
                f"conversation_id={conversation_id} | "
                "success=True"
            )

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

            print(
                "[FACEBOOK SEND] "
                f"stage={exc.stage} | "
                f"status={exc.meta_status} | "
                f"response={exc.response}"
            )

            raise HTTPException(
                status_code=meta_error_status_code(
                    exc
                ),
                detail=exc.to_detail(),
            )

        except Exception as exc:

            db.rollback()

            print(
                "❌ FACEBOOK SEND ERROR:",
                str(exc),
            )

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

            print(
                "[UI SERVICE RESULT] "
                "status=success | "
                f"message_id={external_message_id}"
            )

            print(
                "[UI MEDIA ROUTE END] "
                f"conversation_id={conversation_id} | "
                "success=True"
            )

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

            print(
                "[INSTAGRAM SEND] "
                f"stage={exc.stage} | "
                f"status={exc.meta_status} | "
                f"response={exc.response}"
            )

            raise HTTPException(
                status_code=meta_error_status_code(
                    exc
                ),
                detail=exc.to_detail(),
            )

        except Exception as exc:

            db.rollback()

            print(
                "❌ INSTAGRAM SEND ERROR:",
                str(exc),
            )

            raise HTTPException(
                status_code=500,

                detail=(
                    "Không thể gửi "
                    "Instagram message"
                ),
            )


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
    "/{conversation_id}/send"
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
    file: UploadFile | None = File(
        None
    ),
    db: Session = Depends(
        get_db
    ),
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
    )

    channel = conversation[
        "channel"
    ]

    recipient_id = str(
        conversation[
            "external_user_id"
        ]
    )

    print(
        "[UI MEDIA ROUTE START] "
        f"conversation_id={conversation_id} | "
        f"channel={channel} | "
        f"recipient_id={recipient_id} | "
        f"client_id={client_id!r}"
    )

    results: list[dict] = []
    media_url = None

    try:
        if has_file and file is not None:
            media_url, _ = await prepare_uploaded_image(
                file=file,
                conversation_id=conversation_id,
            )

            results.append(
                await send_and_save_outbound(
                    db=db,
                    conversation_id=conversation_id,
                    channel=channel,
                    recipient_id=recipient_id,
                    image_url=media_url,
                )
            )

        if message_text:
            results.append(
                await send_and_save_outbound(
                    db=db,
                    conversation_id=conversation_id,
                    channel=channel,
                    recipient_id=recipient_id,
                    text_content=message_text,
                )
            )

    except MetaAPIError as exc:
        db.rollback()
        print(
            "[UNIFIED SEND] "
            f"stage={exc.stage} | "
            f"status={exc.meta_status} | "
            f"response={exc.response}"
        )
        raise HTTPException(
            status_code=meta_error_status_code(
                exc
            ),
            detail=exc.to_detail(),
        )

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
            client_id,
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

@router.post(
    "/{conversation_id}/media"
)
def send_media(
    conversation_id: int,
    body: SendMediaRequest,
    db: Session = Depends(
        get_db
    ),
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
        )
    )


    channel = conversation[
        "channel"
    ]

    recipient_id = str(
        conversation[
            "external_user_id"
        ]
    )

    print(
        "[UI MEDIA ROUTE START] "
        f"conversation_id={conversation_id} | "
        f"channel={channel} | "
        f"recipient_id={recipient_id}"
    )


    # =====================================================
    # FACEBOOK IMAGE
    # =====================================================

    if channel == "facebook":

        try:

            print(
                "[UI CALL SERVICE] "
                "service=send_facebook_image | "
                f"recipient_id={recipient_id} | "
                f"media_url={media_url}"
            )

            result = (
                send_facebook_image(
                    recipient_id=
                        recipient_id,

                    image_url=
                        media_url,
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


            print(
                "[UI SERVICE RESULT] "
                "status=success | "
                f"message_id={external_message_id}"
            )

            print(
                "[UI MEDIA ROUTE END] "
                f"conversation_id={conversation_id} | "
                "success=True"
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

                "media_url":
                    media_url,

                "external_message_id":
                    external_message_id,

                "message_id":
                    external_message_id,
            }


        except MetaAPIError as exc:

            db.rollback()

            print(
                "[FACEBOOK SEND] "
                f"stage={exc.stage} | "
                f"status={exc.meta_status} | "
                f"response={exc.response}"
            )

            raise HTTPException(
                status_code=meta_error_status_code(
                    exc
                ),
                detail=exc.to_detail(),
            )


        except Exception as exc:

            db.rollback()

            print(
                "❌ FACEBOOK IMAGE ERROR:",
                str(exc),
            )

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

            print(
                "[INSTAGRAM SEND] "
                f"stage={exc.stage} | "
                f"status={exc.meta_status} | "
                f"response={exc.response}"
            )

            raise HTTPException(
                status_code=meta_error_status_code(
                    exc
                ),
                detail=exc.to_detail(),
            )

        except Exception as exc:

            db.rollback()

            print(
                "❌ INSTAGRAM IMAGE ERROR:",
                str(exc),
            )

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


# =========================================================
# UPLOAD + SEND IMAGE
# =========================================================

@router.post(
    "/{conversation_id}/media/upload"
)
async def upload_and_send_image(
    conversation_id: int,

    file: UploadFile = File(
        ...
    ),

    db: Session = Depends(
        get_db
    ),
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

    print(
        "[UI MEDIA ROUTE START] "
        f"conversation_id={conversation_id}"
    )


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

    print(
        "[UI FILE RECEIVED] "
        f"filename={file.filename!r} | "
        f"content_type={upload_content_type!r} | "
        f"size={len(file_bytes)}"
    )


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

        print(
            "❌ SAVE UPLOAD ERROR:",
            str(exc),
        )

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


    print(
        "[IMAGE NORMALIZE] "
        f"original_format={normalize_info['original_format']} | "
        f"original_mode={normalize_info['original_mode']} | "
        f"original_size={normalize_info['original_size']} | "
        f"normalized_format=JPEG | "
        f"normalized_mode=RGB | "
        f"normalized_path={file_path} | "
        f"normalized_size={len(normalized_bytes)}"
    )

    print(
        "[IMAGE UPLOAD] "
        f"conversation_id={conversation_id} | "
        f"filename={filename} | "
        f"content_type={content_type} | "
        f"size={len(normalized_bytes)} | "
        f"saved_path={file_path} | "
        f"public_url={media_url}"
    )

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

    print(
        "[UI MEDIA ROUTE START] "
        f"conversation_id={conversation_id} | "
        f"channel={channel} | "
        f"recipient_id={recipient_id}"
    )


    # =====================================================
    # FACEBOOK
    # =====================================================

    if channel == "facebook":

        try:

            print(
                "[UI CALL SERVICE] "
                "service=send_facebook_image | "
                f"recipient_id={recipient_id} | "
                f"media_url={media_url}"
            )

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

            print(
                "[FACEBOOK SEND] "
                f"stage={exc.stage} | "
                f"status={exc.meta_status} | "
                f"response={exc.response}"
            )


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

            print(
                "❌ FACEBOOK UPLOAD "
                "IMAGE ERROR:",
                str(exc),
            )


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

            print(
                "[UI CALL SERVICE] "
                "service=send_instagram_image | "
                f"recipient_id={recipient_id} | "
                f"media_url={media_url}"
            )

            result = await run_in_threadpool(
                send_instagram_image,
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

            print(
                "[INSTAGRAM SEND] "
                f"stage={exc.stage} | "
                f"status={exc.meta_status} | "
                f"response={exc.response}"
            )


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

            print(
                "❌ INSTAGRAM UPLOAD "
                "IMAGE ERROR:",
                str(exc),
            )


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


# =========================================================
# AUTO-REPLY SETTINGS ENDPOINTS
# =========================================================

class AutoReplyStatusRequest(BaseModel):
    auto_reply_enabled: bool


@router.get("/auto-reply-status")
async def get_auto_reply_status(db: Session = Depends(get_db)):
    from app.services.auto_reply_service import get_auto_reply_enabled
    return {"auto_reply_enabled": get_auto_reply_enabled(db)}


@router.post("/auto-reply-status")
async def set_auto_reply_status(
    req: AutoReplyStatusRequest,
    db: Session = Depends(get_db),
):
    from app.services.auto_reply_service import set_auto_reply_enabled
    enabled = set_auto_reply_enabled(db, req.auto_reply_enabled)
    return {"auto_reply_enabled": enabled}
