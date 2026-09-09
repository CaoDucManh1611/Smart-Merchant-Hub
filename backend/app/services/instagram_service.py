import logging
from typing import Any

import httpx

from app.core.config import settings
from app.services.meta_errors import MetaAPIError
from app.services.meta_config_service import get_meta_config
from app.services.channel_service import get_single_active_channel
from app.services.channel_credentials import decrypt_token
from app.services.channel_retry import run_with_provider_retry

logger = logging.getLogger(__name__)


# =========================================================
# CONFIG
# =========================================================

INSTAGRAM_MESSAGES_URL = (
    "https://graph.instagram.com/"
    "v22.0/me/messages"
)

INSTAGRAM_GRAPH_BASE_URL = (
    "https://graph.instagram.com/"
    "v22.0"
)

FACEBOOK_GRAPH_BASE_URL = (
    "https://graph.facebook.com/"
    "v22.0"
)


# =========================================================
# HELPERS
# =========================================================

def get_instagram_access_token(db=None, business_id: int | None = None) -> str:
    """
    Lấy Instagram access token
    dùng để gửi tin nhắn Instagram.
    """

    if settings.ENVIRONMENT == "production" and (db is None or business_id is None):
        raise PermissionError("Tenant context is required for production outbound messaging")
    if db is not None and business_id is not None:
        channel = get_single_active_channel(db, business_id, "instagram")
        if not channel.access_token_encrypted:
            raise ValueError("Encrypted Instagram channel token is missing")
        return decrypt_token(channel.access_token_encrypted, settings.CHANNEL_ENCRYPTION_KEY)
    access_token = str(
        settings.INSTAGRAM_ACCESS_TOKEN
        or ""
    ).strip()

    if not access_token:
        raise ValueError(
            "INSTAGRAM_ACCESS_TOKEN "
            "chưa được cấu hình"
        )

    return access_token


def get_instagram_account_id() -> str:
    """
    Lấy Instagram Professional Account ID
    dùng cho Instagram Attachment Upload API.
    """

    account_id = str(
        get_meta_config()["instagram_account_id"] or ""
    ).strip()

    if not account_id:
        raise ValueError(
            "INSTAGRAM_ACCOUNT_ID "
            "chưa được cấu hình"
        )

    return account_id


def get_instagram_page_messaging_config(db=None, business_id: int | None = None) -> tuple[
    str,
    str,
]:
    """
    Instagram inbox hien tai duoc doc qua Page Conversations API,
    nen outbound phai dung Page Send API voi platform=instagram.
    """

    if settings.ENVIRONMENT == "production" and (db is None or business_id is None):
        raise PermissionError("Tenant context is required for production outbound messaging")
    if db is not None and business_id is not None:
        channel = get_single_active_channel(db, business_id, "facebook")
        if not channel.access_token_encrypted:
            raise ValueError("Encrypted Facebook channel token is missing")
        return channel.external_account_id, decrypt_token(
            channel.access_token_encrypted, settings.CHANNEL_ENCRYPTION_KEY
        )
    meta_config = get_meta_config()
    page_id = str(meta_config["facebook_page_id"] or "").strip()

    access_token = str(
        meta_config["facebook_page_access_token"] or ""
    ).strip()

    if not page_id:
        raise ValueError(
            "FACEBOOK_PAGE_ID "
            "chua duoc cau hinh"
        )

    if not access_token:
        raise ValueError(
            "FACEBOOK_PAGE_ACCESS_TOKEN "
            "chua duoc cau hinh"
        )

    return (
        page_id,
        access_token,
    )


def parse_meta_response(
    response: httpx.Response,
) -> dict[str, Any]:
    try:
        return response.json()
    except ValueError:
        return {
            "raw_response":
                response.text,
        }


def validate_recipient(
    recipient_id: str,
) -> str:
    """
    Validate Instagram recipient id.
    """

    recipient_id = str(
        recipient_id
        or ""
    ).strip()

    if not recipient_id:
        raise ValueError(
            "Instagram recipient_id "
            "bị rỗng"
        )

    # Instagram Messaging API expects the Instagram-scoped user ID emitted by
    # the webhook.  These IDs are numeric; placeholders such as USER_111 or
    # a Facebook username otherwise reach Meta and fail with an opaque #100.
    if not (recipient_id.isascii() and recipient_id.isdigit()):
        raise ValueError(
            "Instagram recipient_id phải là Instagram Scoped ID dạng số; "
            "hãy nhận một tin nhắn Instagram thật trước khi trả lời"
        )

    return recipient_id


# =========================================================
# SEND REQUEST CHUNG
# =========================================================

def send_instagram_request(
    recipient_id: str,
    message_payload: dict[str, Any],
    stage: str = "send",
    db=None,
    business_id: int | None = None,
) -> dict[str, Any]:
    """
    Hàm dùng chung để gửi message
    tới Instagram Messaging API.
    """

    recipient_id = (
        validate_recipient(
            recipient_id
        )
    )

    page_id, access_token = (
        get_instagram_page_messaging_config(db=db, business_id=business_id)
    )

    url = (
        f"{FACEBOOK_GRAPH_BASE_URL}/"
        f"{page_id}/messages"
    )

    payload = {
        "recipient": {
            "id": recipient_id,
        },

        "messaging_type":
            "RESPONSE",

        "message":
            message_payload,
    }

    params = {
        "access_token":
            access_token,

        "platform":
            "instagram",
    }

    def _request() -> dict[str, Any]:
        response = httpx.post(
            url,
            params=params,
            json=payload,
            timeout=30,
        )

        logger.info("Instagram provider response status=%s", response.status_code)

        if response.status_code >= 400:
            raise MetaAPIError(
                channel="instagram",
                stage=stage,
                meta_status=response.status_code,
                response=parse_meta_response(
                    response
                ),
            )

        return response.json()

    return run_with_provider_retry(
        provider="instagram",
        operation=stage,
        request=_request,
    )


# =========================================================
# SEND TEXT
# =========================================================

def send_instagram_message(
    recipient_id: str,
    text: str,
    db=None,
    business_id: int | None = None,
) -> dict[str, Any]:
    """
    Gửi text message
    từ CRM sang Instagram.
    """

    # Validate before the request helper so callers/tests that replace the
    # transport still cannot send a non-Instagram-scoped recipient ID.
    recipient_id = validate_recipient(recipient_id)

    text = str(
        text
        or ""
    ).strip()

    if not text:
        raise ValueError(
            "Nội dung tin nhắn "
            "không được để trống"
        )

    logger.info("Sending Instagram text message")

    result = (
        send_instagram_request(
            recipient_id=
                recipient_id,

            message_payload={
                "text":
                    text,
            },
            stage="text_send",
            db=db,
            business_id=business_id,
        )
    )

    logger.info("Instagram text message sent")

    return result


# =========================================================
# UPLOAD IMAGE ATTACHMENT TO META
# =========================================================

def upload_instagram_image_attachment(
    image_url: str,
) -> str:
    """
    Upload ảnh lên Instagram Attachment Upload API.

    Flow:
        image_url
            ↓
        /{INSTAGRAM_ACCOUNT_ID}/message_attachments
            ↓
        attachment_id

    Sau đó attachment_id
    được dùng để gửi Instagram message.
    """

    image_url = str(
        image_url
        or ""
    ).strip()

    if not image_url:
        raise ValueError(
            "image_url không được để trống"
        )

    if not (
        image_url.startswith(
            "https://"
        )
        or image_url.startswith(
            "http://"
        )
    ):
        raise ValueError(
            "image_url phải là "
            "URL http/https"
        )


    instagram_account_id = (
        get_instagram_account_id()
    )

    access_token = (
        get_instagram_access_token()
    )


    url = (
        f"{INSTAGRAM_GRAPH_BASE_URL}/"
        f"{instagram_account_id}/message_attachments"
    )


    params = {
        "access_token":
            access_token,

    }


    payload = {
        "message": {
            "attachment": {
                "type":
                    "image",

                "payload": {
                    "url":
                        image_url,

                    "is_reusable":
                        True,
                },
            },
        },
    }


    logger.info("Uploading Instagram image attachment")


    try:

        response = httpx.post(
            url,
            params=params,
            json=payload,
            timeout=30,
        )


        logger.info("Instagram attachment response status=%s", response.status_code)


        if response.status_code >= 400:
            raise MetaAPIError(
                channel="instagram",
                stage="attachment_upload",
                meta_status=response.status_code,
                response=parse_meta_response(
                    response
                ),
            )


        result = (
            response.json()
        )


        attachment_id = (
            result.get(
                "attachment_id"
            )
        )


        if not attachment_id:

            raise ValueError(
                "Meta không trả về "
                "attachment_id"
            )


        logger.info("Instagram attachment uploaded")


        return str(
            attachment_id
        )


    except MetaAPIError:

        raise


    except httpx.RequestError:
        logger.warning("Instagram attachment upload failed")

        raise


# =========================================================
# SEND IMAGE
# =========================================================

def send_instagram_image(
    recipient_id: str,
    image_url: str,
    db=None,
    business_id: int | None = None,
) -> dict[str, Any]:
    """
    Gửi ảnh từ CRM sang Instagram.

    Theo collection Meta Instagram hiện tại,
    Send API hỗ trợ gửi ảnh trực tiếp bằng URL:

    POST graph.facebook.com/v22.0/{FACEBOOK_PAGE_ID}/messages
    ?platform=instagram
    {
      "recipient": {"id": "<IGSID>"},
      "messaging_type": "RESPONSE",
      "message": {
        "attachment": {
          "type": "image",
          "payload": {"url": "<PUBLIC_IMAGE_URL>"}
        }
      }
    }

    Flow:

    CRM
        ↓
    FastAPI public image URL
        ↓
    Page Send API + platform=instagram
        ↓
    Instagram khách hàng
    """

    recipient_id = (
        validate_recipient(
            recipient_id
        )
    )


    image_url = str(
        image_url
        or ""
    ).strip()


    if not image_url:

        raise ValueError(
            "image_url không được để trống"
        )


    if not (
        image_url.startswith(
            "https://"
        )
        or image_url.startswith(
            "http://"
        )
    ):

        raise ValueError(
            "image_url phải là "
            "URL http/https"
        )


    logger.info("Sending Instagram image message")

    result = (
        send_instagram_request(
            recipient_id=
                recipient_id,

            message_payload={
                "attachment": {
                    "type":
                        "image",

                    "payload": {
                        "url":
                            image_url,
                    },
                },
            },
            stage="image_send",
            db=db,
            business_id=business_id,
        )
    )


    logger.info("Instagram image message sent")

    return result


def send_instagram_media(
    recipient_id: str,
    media_type: str,
    media_url: str,
    caption: str | None = None,
    db=None,
    business_id: int | None = None,
) -> dict[str, Any]:
    """Send a URL attachment through Instagram's Page Send API."""
    media_type = str(media_type or "").strip().lower()
    if media_type == "sticker":
        raise ValueError("Instagram sticker outbound không hỗ trợ URL sticker")
    if media_type not in {"image", "audio", "video", "file"}:
        raise ValueError(f"Instagram không hỗ trợ media_type: {media_type}")
    media_url = str(media_url or "").strip()
    if not media_url.startswith(("http://", "https://")):
        raise ValueError("media_url phải là URL http/https")
    payload: dict[str, Any] = {
        "attachment": {"type": media_type, "payload": {"url": media_url}}
    }
    if caption:
        payload["attachment"]["payload"]["caption"] = str(caption)[:2000]
    return send_instagram_request(
        recipient_id=recipient_id,
        message_payload=payload,
        stage=f"{media_type}_send",
        db=db,
        business_id=business_id,
    )
