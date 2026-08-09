from datetime import datetime, timezone
from typing import Any


def normalize_message(
    channel: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Chuẩn hóa message từ từng nền tảng
    về cùng một format chung.
    """

    if channel == "facebook":
        return normalize_facebook_message(payload)

    if channel == "instagram":
        return normalize_instagram_message(payload)

    return empty_normalized_message(
        channel=channel,
        payload=payload,
    )


def empty_normalized_message(
    channel: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Trả về dữ liệu rỗng khi webhook
    không chứa message hợp lệ.
    """
    return {
        "channel": channel,
        "external_user_id": None,
        "external_message_id": None,
        "content": None,
        "sent_at": None,
        "raw_payload": payload,
    }


def timestamp_to_iso(
    timestamp_ms: int | None,
) -> str | None:
    """
    Chuyển timestamp milliseconds của Meta
    sang ISO datetime UTC.
    """

    if timestamp_ms is None:
        return None

    return datetime.fromtimestamp(
        timestamp_ms / 1000,
        tz=timezone.utc,
    ).isoformat()


# =========================================================
# FACEBOOK
# =========================================================

def normalize_facebook_message(
    payload: dict[str, Any],
) -> dict[str, Any]:
    entries = payload.get("entry", [])

    if not entries:
        return empty_normalized_message(
            channel="facebook",
            payload=payload,
        )

    messaging_events = entries[0].get("messaging", [])

    if not messaging_events:
        return empty_normalized_message(
            channel="facebook",
            payload=payload,
        )

    event = messaging_events[0]

    message = event.get("message", {})

    # Một số event không phải message text
    if not message:
        return empty_normalized_message(
            channel="facebook",
            payload=payload,
        )

    return {
        "channel": "facebook",
        "external_user_id": event.get(
            "sender",
            {},
        ).get("id"),

        "external_message_id": message.get("mid"),

        "content": message.get("text"),

        "sent_at": timestamp_to_iso(
            event.get("timestamp")
        ),

        "raw_payload": payload,
    }


# =========================================================
# INSTAGRAM
# =========================================================

def normalize_instagram_message(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Normalize webhook Instagram Messaging.

    Payload Instagram thường có dạng:

    {
        "object": "instagram",
        "entry": [
            {
                "id": "...",
                "time": ...,
                "messaging": [
                    {
                        "sender": {
                            "id": "..."
                        },
                        "recipient": {
                            "id": "..."
                        },
                        "timestamp": ...,
                        "message": {
                            "mid": "...",
                            "text": "hello"
                        }
                    }
                ]
            }
        ]
    }
    """

    entries = payload.get("entry", [])

    if not entries:
        return empty_normalized_message(
            channel="instagram",
            payload=payload,
        )

    entry = entries[0]

    messaging_events = entry.get("messaging", [])

    if not messaging_events:
        return empty_normalized_message(
            channel="instagram",
            payload=payload,
        )

    event = messaging_events[0]

    message = event.get("message", {})

    if not message:
        return empty_normalized_message(
            channel="instagram",
            payload=payload,
        )

    return {
        "channel": "instagram",

        "external_user_id": event.get(
            "sender",
            {},
        ).get("id"),

        "external_message_id": message.get("mid"),

        "content": message.get("text"),

        "sent_at": timestamp_to_iso(
            event.get("timestamp")
        ),

        "raw_payload": payload,
    }