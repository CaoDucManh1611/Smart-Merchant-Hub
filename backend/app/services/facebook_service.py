from typing import Any

import httpx

from app.core.config import settings


def send_facebook_message(
    recipient_id: str,
    text: str,
) -> dict[str, Any]:
    """
    Gửi tin nhắn Facebook Messenger
    từ Page tới khách hàng.
    """

    page_id = settings.FACEBOOK_PAGE_ID
    access_token = settings.FACEBOOK_PAGE_ACCESS_TOKEN

    if not page_id:
        raise ValueError("FACEBOOK_PAGE_ID chưa được cấu hình")

    if not access_token:
        raise ValueError(
            "FACEBOOK_PAGE_ACCESS_TOKEN chưa được cấu hình"
        )

    url = (
        f"https://graph.facebook.com/"
        f"v22.0/{page_id}/messages"
    )

    payload = {
        "recipient": {
            "id": recipient_id,
        },
        "messaging_type": "RESPONSE",
        "message": {
            "text": text,
        },
    }

    params = {
        "access_token": access_token,
    }

    response = httpx.post(
        url,
        params=params,
        json=payload,
        timeout=10,
    )

    print(
        "FACEBOOK SEND STATUS:",
        response.status_code,
    )

    print(
        "FACEBOOK SEND RESPONSE:",
        response.text,
    )

    response.raise_for_status()

    return response.json()