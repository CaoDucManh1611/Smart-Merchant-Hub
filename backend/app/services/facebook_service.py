from typing import Any

import httpx

from app.services.meta_errors import MetaAPIError
from app.services.meta_config_service import get_meta_config


# =========================================================
# CONFIG
# =========================================================

def get_facebook_config() -> tuple[str, str]:
    """
    Lấy cấu hình Facebook Page.
    """

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
        get_facebook_config()
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

        print(
            "FACEBOOK SEND STATUS:",
            response.status_code,
        )

        print(
            "FACEBOOK SEND RESPONSE:",
            response.text[:1000],
        )

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

    except httpx.RequestError as exc:

        print(
            "❌ FACEBOOK REQUEST ERROR:",
            str(exc),
        )

        raise


# =========================================================
# SEND TEXT
# =========================================================

def send_facebook_message(
    recipient_id: str,
    text: str,
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

    print(
        "📤 FACEBOOK SEND TEXT | "
        f"recipient_id={recipient_id} | "
        f"text={text!r}"
    )

    result = (
        send_facebook_request(
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
        "✅ FACEBOOK TEXT SENT | "
        f"message_id="
        f"{result.get('message_id')}"
    )

    return result


# =========================================================
# SEND IMAGE
# =========================================================

def send_facebook_image(
    recipient_id: str,
    image_url: str,
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

    print(
        "[FACEBOOK IMAGE CONFIG] "
        "endpoint=https://graph.facebook.com/v22.0/{FACEBOOK_PAGE_ID}/messages | "
        "recipient_id_type=PSID | "
        "token_type=FACEBOOK_PAGE_ACCESS_TOKEN | "
        "flow=direct_url"
    )

    print(
        "📤 FACEBOOK SEND IMAGE | "
        f"recipient_id={recipient_id} | "
        f"image_url={image_url}"
    )

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
        )
    )

    print(
        "✅ FACEBOOK IMAGE SENT | "
        f"message_id="
        f"{result.get('message_id')}"
    )

    return result
