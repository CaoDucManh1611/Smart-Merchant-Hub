import logging
from typing import Any

import httpx

from app.services.meta_errors import MetaAPIError
from app.services.meta_config_service import get_meta_config
from app.services.channel_service import get_single_active_channel
from app.core.config import settings

logger = logging.getLogger(__name__)


# =========================================================
# CONFIG
# =========================================================

def get_facebook_config(db=None, business_id: int | None = None) -> tuple[str, str]:
    """
    Lấy cấu hình Facebook Page.
    """

    if settings.ENVIRONMENT == "production" and (db is None or business_id is None):
        raise PermissionError("Tenant context is required for production outbound messaging")
    if db is not None and business_id is not None:
        channel = get_single_active_channel(db, business_id, "facebook")
        if not channel.access_token_encrypted:
            raise ValueError("Encrypted Facebook channel token is missing")
        from app.services.channel_credentials import decrypt_token
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
            "FACEBOOK_PAGE_ID chưa được cấu hình"
        )

    if not access_token:
        raise ValueError(
            "FACEBOOK_PAGE_ACCESS_TOKEN "
            "chưa được cấu hình"
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


# =========================================================
# SEND REQUEST CHUNG
# =========================================================

def send_facebook_request(
    recipient_id: str,
    message_payload: dict[str, Any],
    stage: str = "send",
    db=None,
    business_id: int | None = None,
) -> dict[str, Any]:
    """
    Hàm dùng chung để gửi request
    tới Facebook Messenger API.
    """

    recipient_id = str(
        recipient_id
        or ""
    ).strip()

    if not recipient_id:
        raise ValueError(
            "Facebook recipient_id bị rỗng"
        )

    page_id, access_token = (
        get_facebook_config(db=db, business_id=business_id)
    )

    url = (
        "https://graph.facebook.com/"
        f"v22.0/{page_id}/messages"
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
    }

    try:

        response = httpx.post(
            url,
            params=params,
            json=payload,
            timeout=20,
        )

        logger.info("Facebook provider response status=%s", response.status_code)

        if response.status_code >= 400:
            raise MetaAPIError(
                channel="facebook",
                stage=stage,
                meta_status=response.status_code,
                response=parse_meta_response(
                    response
                ),
            )

        return response.json()

    except MetaAPIError:

        raise

    except httpx.RequestError:
        logger.warning("Facebook provider request failed")

        raise


# =========================================================
# SEND TEXT
# =========================================================

def send_facebook_message(
    recipient_id: str,
    text: str,
    db=None,
    business_id: int | None = None,
) -> dict[str, Any]:
    """
    Gửi text message
    từ Facebook Page tới khách hàng.
    """

    text = str(
        text
        or ""
    ).strip()

    if not text:
        raise ValueError(
            "Nội dung tin nhắn "
            "không được để trống"
        )

    logger.info("Sending Facebook text message")

    result = (
        send_facebook_request(
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

    logger.info("Facebook text message sent")

    return result


# =========================================================
# SEND IMAGE
# =========================================================

def send_facebook_image(
    recipient_id: str,
    image_url: str,
    db=None,
    business_id: int | None = None,
) -> dict[str, Any]:
    """
    Gửi ảnh từ CRM sang Facebook Messenger.

    image_url phải là URL public
    mà Meta truy cập được.

    Ví dụ:
        https://example.com/image.jpg
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
            "image_url phải là URL "
            "http/https"
        )

    logger.info("Sending Facebook image message")

    result = (
        send_facebook_request(
            recipient_id=
                recipient_id,

            message_payload={
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
            stage="image_send",
            db=db,
            business_id=business_id,
        )
    )

    logger.info("Facebook image message sent")

    return result


def send_facebook_media(
    recipient_id: str,
    media_type: str,
    media_url: str,
    caption: str | None = None,
    db=None,
    business_id: int | None = None,
) -> dict[str, Any]:
    """Send a provider-supported URL attachment through Messenger."""
    media_type = str(media_type or "").strip().lower()
    if media_type == "sticker":
        raise ValueError("Facebook sticker outbound cần sticker_id; URL sticker không được hỗ trợ")
    if media_type not in {"image", "audio", "video", "file"}:
        raise ValueError(f"Facebook không hỗ trợ media_type: {media_type}")
    media_url = str(media_url or "").strip()
    if not media_url.startswith(("http://", "https://")):
        raise ValueError("media_url phải là URL http/https")
    payload = {
        "attachment": {
            "type": media_type,
            "payload": {"url": media_url, "is_reusable": media_type == "image"},
        }
    }
    if caption:
        # Messenger attachment captions are represented as text alongside the
        # attachment; keeping it in the payload is accepted by newer Graph API
        # versions and ignored by older ones.
        payload["attachment"]["payload"]["caption"] = str(caption)[:2000]
    return send_facebook_request(
        recipient_id=recipient_id,
        message_payload=payload,
        stage=f"{media_type}_send",
        db=db,
        business_id=business_id,
    )
