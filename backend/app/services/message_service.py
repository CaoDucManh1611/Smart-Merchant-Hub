from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.message_repository import save_message


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
        "raw_payload": payload,
    }


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

    messaging_events = entries[0].get(
        "messaging",
        [],
    )

    if not messaging_events:
        return empty_normalized_message(
            channel="facebook",
            payload=payload,
        )

    event = messaging_events[0]

    message = event.get("message", {})

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
        "external_message_id": message.get(
            "mid"
        ),
        "content": message.get("text"),
        "raw_payload": payload,
    }


# =========================================================
# INSTAGRAM
# =========================================================

def fetch_instagram_message_data(
    mid: str,
    access_token: str,
) -> dict[str, Any]:
    """
    Gọi Graph API để lấy:
    - nội dung message
    - sender_id
    """

    if not access_token:
        print(
            "[WARN] FACEBOOK_PAGE_ACCESS_TOKEN "
            "chưa được set trong .env"
        )

        return {
            "content": None,
            "sender_id": None,
        }

    if not mid:
        print(
            "[WARN] Instagram message mid rỗng"
        )

        return {
            "content": None,
            "sender_id": None,
        }

    url = (
        f"https://graph.facebook.com/"
        f"v22.0/{mid}"
    )

    params = {
        "access_token": access_token,
        "fields": "message,from",
    }

    try:
        print(
            "[INFO] Gọi Graph API "
            f"(fields=message,from): {url}"
        )

        response = httpx.get(
            url,
            params=params,
            timeout=5,
        )

        print(
            "[INFO] Graph API status: "
            f"{response.status_code}, "
            f"body: {response.text[:300]}"
        )

        if response.status_code == 200:
            data = response.json()

            return {
                "content": data.get("message"),
                "sender_id": data.get(
                    "from",
                    {},
                ).get("id"),
            }

    except Exception as e:
        print(
            "[WARN] "
            "fetch_instagram_message_data "
            f"exception: {e}"
        )

    return {
        "content": None,
        "sender_id": None,
    }


def normalize_instagram_message(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Normalize webhook Instagram Messaging.
    """

    entries = payload.get(
        "entry",
        [],
    )

    if not entries:
        return empty_normalized_message(
            channel="instagram",
            payload=payload,
        )

    entry = entries[0]

    messaging_events = entry.get(
        "messaging",
        [],
    )

    if not messaging_events:
        return empty_normalized_message(
            channel="instagram",
            payload=payload,
        )

    event = messaging_events[0]

    # ==========================================
    # CASE 1:
    # Instagram gửi message bình thường
    # ==========================================

    message = event.get(
        "message",
        {},
    )

    if message:
        return {
            "channel": "instagram",
            "external_user_id": event.get(
                "sender",
                {},
            ).get("id"),
            "external_message_id": message.get(
                "mid"
            ),
            "content": message.get(
                "text"
            ),
            "raw_payload": payload,
        }

    # ==========================================
    # CASE 2:
    # Instagram gửi message_edit
    # num_edit = 0
    # ==========================================

    message_edit = event.get(
        "message_edit",
        {},
    )

    if (
        message_edit
        and message_edit.get(
            "num_edit",
            -1,
        ) == 0
    ):

        mid = message_edit.get(
            "mid"
        )

        from app.core.config import settings

        access_token = (
            settings.FACEBOOK_PAGE_ACCESS_TOKEN
        )

        print(
            "[INFO] Instagram đang sử dụng "
            "FACEBOOK_PAGE_ACCESS_TOKEN"
        )

        result = fetch_instagram_message_data(
            mid=mid,
            access_token=access_token,
        )

        sender_id = (
            result["sender_id"]
            or event.get(
                "sender",
                {},
            ).get("id")
        )

        content = result["content"]

        print(
            "[INFO] "
            "message_edit(num_edit=0) "
            f"content={content!r}, "
            f"sender_id={sender_id!r}"
        )

        return {
            "channel": "instagram",
            "external_user_id": sender_id,
            "external_message_id": mid,
            "content": content,
            "raw_payload": payload,
        }

    return empty_normalized_message(
        channel="instagram",
        payload=payload,
    )


# =========================================================
# DATABASE
# =========================================================

def process_and_save_message(
    db: Session,
    message: dict[str, Any],
) -> bool:
    """
    Luồng:

    1. Bỏ qua outbound echo của chính shop Instagram
    2. Validate dữ liệu
    3. Tìm / tạo customer
    4. Tìm / tạo conversation open
    5. Gắn conversation_id
    6. Gắn direction = inbound
    7. Lưu message

    Return:
        True  -> lưu thành công
        False -> message bị bỏ qua / không hợp lệ
    """

    channel = message.get(
        "channel"
    )

    external_user_id = message.get(
        "external_user_id"
    )

    external_message_id = message.get(
        "external_message_id"
    )

    # ==========================================
    # 0. BỎ QUA OUTBOUND ECHO INSTAGRAM
    # ==========================================

    if channel == "instagram":
        from app.core.config import settings

        instagram_account_id = str(
            settings.INSTAGRAM_ACCOUNT_ID
        ).strip()

        sender_id = (
            str(external_user_id).strip()
            if external_user_id is not None
            else ""
        )

        if (
            instagram_account_id
            and sender_id == instagram_account_id
        ):
            print(
                "🔁 INSTAGRAM OUTBOUND ECHO IGNORED | "
                f"sender_id={sender_id}"
            )

            return False

    # ==========================================
    # 1. VALIDATE
    # ==========================================

    if (
        not channel
        or not external_user_id
    ):
        print(
            "⚠️ Bỏ qua webhook: "
            "không có channel "
            "hoặc external_user_id"
        )

        return False

    if not external_message_id:
        print(
            "⚠️ Bỏ qua webhook: "
            "không có external_message_id"
        )

        return False

    # ==========================================
    # 2. TÌM CUSTOMER
    # ==========================================

    customer = db.execute(
        text("""
            SELECT id
            FROM customers
            WHERE channel = :channel
              AND external_user_id = :external_user_id
            LIMIT 1
        """),
        {
            "channel": channel,
            "external_user_id":
                external_user_id,
        },
    ).first()

    # ==========================================
    # 3. CHƯA CÓ CUSTOMER -> TẠO
    # ==========================================

    if customer is None:
        customer = db.execute(
            text("""
                INSERT INTO customers (
                    channel,
                    external_user_id
                )
                VALUES (
                    :channel,
                    :external_user_id
                )
                RETURNING id
            """),
            {
                "channel": channel,
                "external_user_id":
                    external_user_id,
            },
        ).first()

        db.commit()

        print(
            "✅ CREATED CUSTOMER "
            f"id={customer.id}"
        )

    customer_id = customer.id

    # ==========================================
    # 4. TÌM CONVERSATION OPEN
    # ==========================================

    conversation = db.execute(
        text("""
            SELECT id
            FROM conversations
            WHERE customer_id = :customer_id
              AND channel = :channel
              AND status = 'open'
            ORDER BY id DESC
            LIMIT 1
        """),
        {
            "customer_id": customer_id,
            "channel": channel,
        },
    ).first()

    # ==========================================
    # 5. CHƯA CÓ CONVERSATION -> TẠO
    # ==========================================

    if conversation is None:
        conversation = db.execute(
            text("""
                INSERT INTO conversations (
                    customer_id,
                    channel,
                    status
                )
                VALUES (
                    :customer_id,
                    :channel,
                    'open'
                )
                RETURNING id
            """),
            {
                "customer_id": customer_id,
                "channel": channel,
            },
        ).first()

        db.commit()

        print(
            "✅ CREATED CONVERSATION "
            f"id={conversation.id}"
        )

    conversation_id = conversation.id

    # ==========================================
    # 6. GẮN CONVERSATION ID + DIRECTION
    # ==========================================

    message["conversation_id"] = conversation_id

    # Webhook từ khách gửi vào CRM
    message["direction"] = "inbound"

    # ==========================================
    # 7. LƯU MESSAGE
    # ==========================================

    save_message(
        db=db,
        message=message,
    )

    print(
        "✅ MESSAGE SAVED | "
        f"customer_id={customer_id} | "
        f"conversation_id={conversation_id} | "
        f"direction=inbound | "
        f"external_message_id="
        f"{external_message_id}"
    )

    return True