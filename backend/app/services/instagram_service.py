from typing import Any

import httpx

from app.core.config import settings


def send_instagram_message(
    recipient_id: str,
    text: str,
) -> dict[str, Any]:
    """
    Gửi tin nhắn Instagram từ tài khoản Professional
    tới khách hàng thông qua Instagram API.

    recipient_id:
        Instagram-scoped user ID (IGSID) của khách.

    text:
        Nội dung tin nhắn.
    """

    access_token = settings.INSTAGRAM_ACCESS_TOKEN

    # =====================================================
    # VALIDATE CONFIG
    # =====================================================

    if not access_token:
        raise ValueError(
            "INSTAGRAM_ACCESS_TOKEN chưa được cấu hình"
        )

    if not recipient_id:
        raise ValueError(
            "Instagram recipient_id bị rỗng"
        )

    if not text or not text.strip():
        raise ValueError(
            "Nội dung tin nhắn không được để trống"
        )

    # =====================================================
    # GRAPH API
    # =====================================================

    url = "https://graph.instagram.com/v22.0/me/messages"

    payload = {
        "recipient": {
            "id": recipient_id,
        },
        "message": {
            "text": text,
        },
    }

    params = {
        "access_token": access_token,
    }

    # =====================================================
    # SEND REQUEST
    # =====================================================

    try:
        print(
            "📤 INSTAGRAM SEND | "
            f"recipient_id={recipient_id} | "
            f"text={text!r}"
        )

        response = httpx.post(
            url,
            params=params,
            json=payload,
            timeout=10,
        )

        print(
            "INSTAGRAM SEND STATUS:",
            response.status_code,
        )

        print(
            "INSTAGRAM SEND RESPONSE:",
            response.text,
        )

        response.raise_for_status()

        result = response.json()

        print(
            "✅ INSTAGRAM MESSAGE SENT | "
            f"message_id={result.get('message_id')}"
        )

        return result

    except httpx.HTTPStatusError as e:
        print(
            "❌ INSTAGRAM GRAPH API ERROR | "
            f"status={e.response.status_code} | "
            f"body={e.response.text}"
        )

        raise

    except httpx.RequestError as e:
        print(
            "❌ INSTAGRAM REQUEST ERROR:",
            str(e),
        )

        raise