from datetime import datetime, timezone
from typing import Any

import httpx


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


def fetch_instagram_message_data(mid: str, access_token: str) -> dict[str, Any]:
    """
    Gọi Graph API 1 lần để lấy cả nội dung tin nhắn và người gửi.
    Trả về dict: {"content": str|None, "sender_id": str|None}
    """
    if not access_token:
        print("[WARN] fetch_instagram_message_data: INSTAGRAM_ACCESS_TOKEN chưa được set trong .env!")
        return {"content": None, "sender_id": None}
    if not mid:
        print("[WARN] fetch_instagram_message_data: mid rỗng")
        return {"content": None, "sender_id": None}

    url = f"https://graph.facebook.com/v22.0/{mid}"
    params = {
        "access_token": access_token,
        "fields": "message,from",
    }
    try:
        print(f"[INFO] Gọi Graph API (fields=message,from): {url}")
        resp = httpx.get(url, params=params, timeout=5)
        print(f"[INFO] Graph API status: {resp.status_code}, body: {resp.text[:300]}")
        if resp.status_code == 200:
            data = resp.json()
            return {
                "content": data.get("message"),
                "sender_id": data.get("from", {}).get("id"),
            }
    except Exception as e:
        print(f"[WARN] fetch_instagram_message_data exception: {e}")

    return {"content": None, "sender_id": None}


def normalize_instagram_message(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Normalize webhook Instagram Messaging.
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

    # --- Trường hợp 1: messages event thông thường ---
    message = event.get("message", {})
    if message:
        return {
            "channel": "instagram",
            "external_user_id": event.get("sender", {}).get("id"),
            "external_message_id": message.get("mid"),
            "content": message.get("text"),
            "sent_at": timestamp_to_iso(event.get("timestamp")),
            "raw_payload": payload,
        }

    # --- Trường hợp 2: message_edit với num_edit=0 ---
    # Instagram API v26+ gửi tin nhắn MỚI dưới dạng message_edit num_edit=0
    # Phải gọi Graph API để lấy text & sender_id.
    message_edit = event.get("message_edit", {})
    if message_edit and message_edit.get("num_edit", -1) == 0:
        mid = message_edit.get("mid")
        from app.core.config import settings
        access_token = (
            settings.INSTAGRAM_ACCESS_TOKEN
            or settings.FACEBOOK_PAGE_ACCESS_TOKEN
        )
        res = fetch_instagram_message_data(mid, access_token)
        sender_id = res["sender_id"] or event.get("sender", {}).get("id")
        content = res["content"]
        print(f"[INFO] message_edit(num_edit=0) fetched content: {content!r}, sender_id: {sender_id!r}")
        return {
            "channel": "instagram",
            "external_user_id": sender_id,
            "external_message_id": mid,
            "content": content,
            "sent_at": timestamp_to_iso(event.get("timestamp")),
            "raw_payload": payload,
        }

    return empty_normalized_message(
        channel="instagram",
        payload=payload,
    )