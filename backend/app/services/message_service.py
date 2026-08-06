from datetime import datetime, timezone
from typing import Any


def normalize_message(
    channel: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if channel == "facebook":
        return normalize_facebook_message(payload)

    return {
        "channel": channel,
        "external_user_id": None,
        "external_message_id": None,
        "content": None,
        "sent_at": None,
        "raw_payload": payload,
    }


def normalize_facebook_message(
    payload: dict[str, Any],
) -> dict[str, Any]:
    entries = payload.get("entry", [])

    # Meta đôi khi gửi payload thử với entry rỗng
    if not entries:
        return {
            "channel": "facebook",
            "external_user_id": None,
            "external_message_id": None,
            "content": None,
            "sent_at": None,
            "raw_payload": payload,
        }

    messaging_events = entries[0].get("messaging", [])

    if not messaging_events:
        return {
            "channel": "facebook",
            "external_user_id": None,
            "external_message_id": None,
            "content": None,
            "sent_at": None,
            "raw_payload": payload,
        }

    event = messaging_events[0]
    message = event.get("message", {})

    timestamp_ms = event.get("timestamp")
    sent_at = None

    if timestamp_ms is not None:
        sent_at = datetime.fromtimestamp(
            timestamp_ms / 1000,
            tz=timezone.utc,
        ).isoformat()

    return {
        "channel": "facebook",
        "external_user_id": event.get("sender", {}).get("id"),
        "external_message_id": message.get("mid"),
        "content": message.get("text"),
        "sent_at": sent_at,
        "raw_payload": payload,
    }