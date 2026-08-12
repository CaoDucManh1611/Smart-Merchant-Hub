from typing import Any

import httpx

from app.core.config import settings
from app.services.meta_errors import MetaAPIError


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

def get_instagram_access_token() -> str:
    """
    Lấy Instagram access token
    dùng để gửi tin nhắn Instagram.
    """

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
        settings.INSTAGRAM_ACCOUNT_ID
        or ""
    ).strip()

    if not account_id:
        raise ValueError(
            "INSTAGRAM_ACCOUNT_ID "
            "chưa được cấu hình"
        )

    return account_id


def get_instagram_page_messaging_config() -> tuple[
    str,
    str,
]:
    """
    Instagram inbox hien tai duoc doc qua Page Conversations API,
    nen outbound phai dung Page Send API voi platform=instagram.
    """

    page_id = str(
        settings.FACEBOOK_PAGE_ID
        or ""
    ).strip()

    access_token = str(
        settings.FACEBOOK_PAGE_ACCESS_TOKEN
        or ""
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

    return recipient_id


# =========================================================
# SEND REQUEST CHUNG
# =========================================================

def send_instagram_request(
    recipient_id: str,
    message_payload: dict[str, Any],
    stage: str = "send",
) -> dict[str, Any]:
    """
    Hàm dùng chung để gửi message
    tới Instagram Messaging API.
    """

    page_id, access_token = (
        get_instagram_page_messaging_config()
    )

    recipient_id = (
        validate_recipient(
            recipient_id
        )
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

    try:

        response = httpx.post(
            url,
            params=params,
            json=payload,
            timeout=30,
        )

        print(
            "INSTAGRAM SEND STATUS:",
            response.status_code,
        )

        print(
            "INSTAGRAM SEND RESPONSE:",
            response.text[:1500],
        )

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

    except MetaAPIError:

        raise

    except httpx.RequestError as exc:

        print(
            "❌ INSTAGRAM REQUEST ERROR:",
            str(exc),
        )

        raise


# =========================================================
# SEND TEXT
# =========================================================

def send_instagram_message(
    recipient_id: str,
    text: str,
) -> dict[str, Any]:
    """
    Gửi text message
    từ CRM sang Instagram.
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

    print(
        "📤 INSTAGRAM SEND TEXT | "
        f"recipient_id={recipient_id} | "
        f"text={text!r}"
    )

    result = (
        send_instagram_request(
            recipient_id=
                recipient_id,

            message_payload={
                "text":
                    text,
            },
            stage="text_send",
        )
    )

    print(
        "✅ INSTAGRAM TEXT SENT | "
        f"message_id="
        f"{result.get('message_id')}"
    )

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


    print(
        "[INSTAGRAM ATTACHMENT] "
        f"endpoint={url} | "
        f"image_url={image_url}"
    )


    try:

        response = httpx.post(
            url,
            params=params,
            json=payload,
            timeout=30,
        )


        print(
            "INSTAGRAM ATTACHMENT "
            "UPLOAD STATUS:",
            response.status_code,
        )


        print(
            "INSTAGRAM ATTACHMENT "
            "UPLOAD RESPONSE:",
            response.text[:1500],
        )


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


        print(
            "✅ INSTAGRAM ATTACHMENT "
            "UPLOADED | "
            f"attachment_id="
            f"{attachment_id}"
        )


        return str(
            attachment_id
        )


    except MetaAPIError:

        raise


    except httpx.RequestError as exc:

        print(
            "❌ INSTAGRAM ATTACHMENT "
            "REQUEST ERROR:",
            str(exc),
        )

        raise


# =========================================================
# SEND IMAGE
# =========================================================

def send_instagram_image(
    recipient_id: str,
    image_url: str,
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


    print(
        "[INSTAGRAM IMAGE CONFIG] "
        "endpoint=https://graph.facebook.com/v22.0/{FACEBOOK_PAGE_ID}/messages | "
        "platform=instagram | "
        "recipient_id_type=IGSID_FROM_PAGE_CONVERSATIONS | "
        "token_type=FACEBOOK_PAGE_ACCESS_TOKEN | "
        "flow=direct_url"
    )

    print(
        "[INSTAGRAM SEND] "
        f"recipient_id={recipient_id} | "
        f"image_url={image_url}"
    )

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
        )
    )


    print(
        "[INSTAGRAM SEND] "
        f"message_id="
        f"{result.get('message_id')}"
    )

    return result
