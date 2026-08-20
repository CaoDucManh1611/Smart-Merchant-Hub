from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.message_repository import save_message
from app.services.meta_config_service import get_meta_config


# =========================================================
# NORMALIZE
# =========================================================

def normalize_message(
    channel: str,
    payload: dict[str, Any],
) -> dict[str, Any]:

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

    return {
        "channel": channel,
        "external_user_id": None,
        "external_message_id": None,
        "content": None,
        "media_type": None,
        "media_url": None,
        "raw_payload": payload,
    }


# =========================================================
# ATTACHMENT HELPER
# =========================================================

def extract_attachment(
    message: dict[str, Any],
) -> dict[str, Any]:
    """
    Lấy attachment đầu tiên từ webhook message.

    Hỗ trợ:
    - image
    - video
    - file
    - attachment fallback
    """

    attachments = message.get(
        "attachments",
        [],
    )

    if not attachments:
        return {
            "media_type": None,
            "media_url": None,
        }

    first = attachments[0]

    # =====================================================
    # IMAGE
    # =====================================================

    image_url = (
        first.get(
            "image_data",
            {},
        ).get(
            "url"
        )
    )

    if image_url:
        return {
            "media_type": "image",
            "media_url": image_url,
        }


    # =====================================================
    # VIDEO
    # =====================================================

    video_url = first.get(
        "video_url"
    )

    if video_url:
        return {
            "media_type": "video",
            "media_url": video_url,
        }


    # =====================================================
    # FILE
    # =====================================================

    file_url = first.get(
        "file_url"
    )

    if file_url:
        return {
            "media_type": "file",
            "media_url": file_url,
        }


    # =====================================================
    # PAYLOAD.URL
    # =====================================================

    payload = first.get(
        "payload",
        {},
    )

    media_url = payload.get(
        "url"
    )

    media_type = first.get(
        "type"
    )

    if media_url:

        if media_type in (
            "image",
            "photo",
        ):
            media_type = "image"

        elif media_type in (
            "video",
            "reel",
        ):
            media_type = "video"

        elif media_type in (
            "file",
            "audio",
        ):
            media_type = media_type

        else:
            media_type = (
                media_type
                or "attachment"
            )

        return {
            "media_type": media_type,
            "media_url": media_url,
        }


    return {
        "media_type": (
            media_type
            or "attachment"
        ),
        "media_url": None,
    }


# =========================================================
# FACEBOOK - NORMALIZE
# =========================================================

def normalize_facebook_message(
    payload: dict[str, Any],
) -> dict[str, Any]:

    entries = payload.get(
        "entry",
        [],
    )

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

    message = event.get(
        "message",
        {},
    )

    if not message:
        return empty_normalized_message(
            channel="facebook",
            payload=payload,
        )

    # Facebook echoes Page-sent messages back to the webhook. Do not treat
    # those echoes as new customer questions or trigger another RAG reply.
    if message.get("is_echo"):
        print("🔁 FACEBOOK OUTBOUND ECHO IGNORED")
        return empty_normalized_message(
            channel="facebook",
            payload=payload,
        )

    attachment = extract_attachment(
        message
    )

    return {
        "channel":
            "facebook",

        "external_user_id":
            event.get(
                "sender",
                {},
            ).get("id"),

        "external_message_id":
            message.get(
                "mid"
            ),

        "content":
            message.get(
                "text"
            ),

        "media_type":
            attachment.get(
                "media_type"
            ),

        "media_url":
            attachment.get(
                "media_url"
            ),

        "raw_payload":
            payload,
    }


# =========================================================
# FACEBOOK - CUSTOMER PROFILE
# =========================================================

def fetch_facebook_customer_profile(
    external_user_id: str,
) -> dict[str, Any]:

    access_token = str(
        get_meta_config()["facebook_page_access_token"] or ""
    ).strip()

    if not access_token:

        print(
            "⚠️ FACEBOOK PROFILE SKIPPED | "
            "FACEBOOK_PAGE_ACCESS_TOKEN chưa có"
        )

        return {
            "name": None,
            "avatar_url": None,
        }

    if not external_user_id:

        return {
            "name": None,
            "avatar_url": None,
        }

    url = (
        "https://graph.facebook.com/"
        f"{external_user_id}"
    )

    params = {
        "fields":
            "name,profile_pic",

        "access_token":
            access_token,
    }

    try:

        print(
            "🔎 FETCH FACEBOOK PROFILE | "
            f"user_id={external_user_id}"
        )

        response = httpx.get(
            url,
            params=params,
            timeout=10,
        )

        print(
            "FACEBOOK PROFILE STATUS:",
            response.status_code,
        )

        if response.status_code != 200:

            print(
                "⚠️ FACEBOOK PROFILE ERROR:",
                response.text[:500],
            )

            return {
                "name": None,
                "avatar_url": None,
            }

        data = response.json()

        name = data.get(
            "name"
        )

        avatar_url = data.get(
            "profile_pic"
        )

        print(
            "✅ FACEBOOK PROFILE RECEIVED | "
            f"name={name!r}"
        )

        return {
            "name": name,
            "avatar_url": avatar_url,
        }

    except Exception as exc:

        print(
            "⚠️ FACEBOOK PROFILE EXCEPTION:",
            exc,
        )

        return {
            "name": None,
            "avatar_url": None,
        }


# =========================================================
# INSTAGRAM - CUSTOMER PROFILE
# =========================================================

def fetch_instagram_customer_profile(
    external_user_id: str,
) -> dict[str, Any]:

    access_token = str(
        get_meta_config()["facebook_page_access_token"] or ""
    ).strip()

    if not access_token:

        print(
            "⚠️ INSTAGRAM PROFILE SKIPPED | "
            "FACEBOOK_PAGE_ACCESS_TOKEN chưa có"
        )

        return {
            "name": None,
            "username": None,
            "avatar_url": None,
        }

    if not external_user_id:

        return {
            "name": None,
            "username": None,
            "avatar_url": None,
        }

    url = (
        "https://graph.facebook.com/"
        f"v22.0/{external_user_id}"
    )

    params = {
        "fields":
            "name,username,profile_pic",

        "access_token":
            access_token,
    }

    try:

        print(
            "🔎 FETCH INSTAGRAM PROFILE | "
            f"user_id={external_user_id}"
        )

        response = httpx.get(
            url,
            params=params,
            timeout=10,
        )

        print(
            "INSTAGRAM PROFILE STATUS:",
            response.status_code,
        )

        if response.status_code != 200:

            print(
                "⚠️ INSTAGRAM PROFILE ERROR:",
                response.text[:500],
            )

            return {
                "name": None,
                "username": None,
                "avatar_url": None,
            }

        data = response.json()

        name = data.get(
            "name"
        )

        username = data.get(
            "username"
        )

        avatar_url = data.get(
            "profile_pic"
        )

        display_name = (
            name
            or (
                f"@{username}"
                if username
                else None
            )
        )

        print(
            "✅ INSTAGRAM PROFILE RECEIVED | "
            f"name={display_name!r} | "
            f"username={username!r}"
        )

        return {
            "name":
                display_name,

            "username":
                username,

            "avatar_url":
                avatar_url,
        }

    except Exception as exc:

        print(
            "⚠️ INSTAGRAM PROFILE EXCEPTION:",
            exc,
        )

        return {
            "name": None,
            "username": None,
            "avatar_url": None,
        }


# =========================================================
# INSTAGRAM - FETCH MESSAGE DATA
# =========================================================

def fetch_instagram_message_data(
    mid: str,
    access_token: str,
) -> dict[str, Any]:
    """
    Lấy message Instagram từ Graph API.

    Bao gồm:
    - content
    - sender_id
    - media_type
    - media_url
    """

    if not access_token:

        print(
            "[WARN] FACEBOOK_PAGE_ACCESS_TOKEN "
            "chưa được set trong .env"
        )

        return {
            "content": None,
            "sender_id": None,
            "media_type": None,
            "media_url": None,
        }


    if not mid:

        print(
            "[WARN] Instagram message mid rỗng"
        )

        return {
            "content": None,
            "sender_id": None,
            "media_type": None,
            "media_url": None,
        }


    url = (
        "https://graph.facebook.com/"
        f"v22.0/{mid}"
    )

    params = {
        "access_token":
            access_token,

        "fields":
            "message,from,attachments",
    }


    try:

        print(
            "[INFO] Gọi Graph API "
            "(fields=message,from,attachments): "
            f"{url}"
        )

        response = httpx.get(
            url,
            params=params,
            timeout=10,
        )

        print(
            "[INFO] Graph API status: "
            f"{response.status_code}, "
            f"body: {response.text[:1000]}"
        )


        if response.status_code != 200:

            return {
                "content": None,
                "sender_id": None,
                "media_type": None,
                "media_url": None,
            }


        data = response.json()

        media_type = None
        media_url = None


        # =================================================
        # ATTACHMENTS
        # =================================================

        attachments_data = data.get(
            "attachments"
        )


        # =================================================
        # DẠNG 1:
        # attachments = [...]
        # =================================================

        if isinstance(
            attachments_data,
            list,
        ):

            if attachments_data:

                first = (
                    attachments_data[0]
                )

                (
                    media_type,
                    media_url,
                ) = parse_instagram_attachment(
                    first
                )


        # =================================================
        # DẠNG 2:
        # attachments = {
        #     "data": [...]
        # }
        # =================================================

        elif isinstance(
            attachments_data,
            dict,
        ):

            attachment_list = (
                attachments_data.get(
                    "data",
                    [],
                )
            )

            if attachment_list:

                first = (
                    attachment_list[0]
                )

                (
                    media_type,
                    media_url,
                ) = parse_instagram_attachment(
                    first
                )


        print(
            "📎 INSTAGRAM MEDIA PARSED | "
            f"media_type={media_type!r} | "
            f"media_url={media_url!r}"
        )


        return {
            "content":
                data.get(
                    "message"
                ),

            "sender_id":
                data.get(
                    "from",
                    {},
                ).get(
                    "id"
                ),

            "media_type":
                media_type,

            "media_url":
                media_url,
        }


    except Exception as exc:

        print(
            "[WARN] "
            "fetch_instagram_message_data "
            f"exception: {exc}"
        )


    return {
        "content": None,
        "sender_id": None,
        "media_type": None,
        "media_url": None,
    }


# =========================================================
# INSTAGRAM ATTACHMENT PARSER
# =========================================================

def parse_instagram_attachment(
    first: dict[str, Any],
) -> tuple[
    str | None,
    str | None,
]:
    """
    Parse attachment Instagram Graph API.

    Ưu tiên:
    1. image_data.url
    2. video_url
    3. file_url
    4. generic_template.media_url
    5. payload.url
    6. direct url
    """

    # =====================================================
    # IMAGE
    # =====================================================

    image_data = first.get(
        "image_data",
        {},
    )

    image_url = image_data.get(
        "url"
    )

    if image_url:

        return (
            "image",
            image_url,
        )


    # =====================================================
    # VIDEO
    # =====================================================

    video_url = first.get(
        "video_url"
    )

    if video_url:

        return (
            "video",
            video_url,
        )


    # =====================================================
    # FILE
    # =====================================================

    file_url = first.get(
        "file_url"
    )

    if file_url:

        return (
            "file",
            file_url,
        )


    # =====================================================
    # GENERIC TEMPLATE MEDIA URL
    # =====================================================

    generic_template = first.get(
        "generic_template",
        {},
    )

    generic_media_url = generic_template.get(
        "media_url"
    )

    if generic_media_url:

        return (
            "image",
            generic_media_url,
        )


    # =====================================================
    # PAYLOAD URL
    # =====================================================

    payload = first.get(
        "payload",
        {},
    )

    payload_url = payload.get(
        "url"
    )

    raw_type = str(
        first.get(
            "type"
        )
        or ""
    ).lower()


    if payload_url:

        if raw_type in (
            "image",
            "photo",
        ):

            return (
                "image",
                payload_url,
            )


        if raw_type in (
            "video",
            "reel",
        ):

            return (
                "video",
                payload_url,
            )


        if raw_type in (
            "file",
            "audio",
        ):

            return (
                raw_type,
                payload_url,
            )


        return (
            "attachment",
            payload_url,
        )


    # =====================================================
    # URL FIELD FALLBACK
    # =====================================================

    direct_url = first.get(
        "url"
    )

    if direct_url:

        if raw_type in (
            "image",
            "photo",
        ):

            return (
                "image",
                direct_url,
            )


        if raw_type in (
            "video",
            "reel",
        ):

            return (
                "video",
                direct_url,
            )


        return (
            raw_type
            or "attachment",
            direct_url,
        )


    return (
        raw_type
        or None,
        None,
    )


# =========================================================
# INSTAGRAM - NORMALIZE
# =========================================================

def normalize_instagram_message(
    payload: dict[str, Any],
) -> dict[str, Any]:

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

    # Meta emits message_edit events after delivery. They are not new
    # customer messages and must not trigger another RAG reply.
    if event.get("message_edit"):
        print("🔁 INSTAGRAM MESSAGE_EDIT IGNORED")
        return empty_normalized_message(
            channel="instagram",
            payload=payload,
        )


    # =====================================================
    # CASE 1:
    # MESSAGE BÌNH THƯỜNG
    # =====================================================

    message = event.get(
        "message",
        {},
    )


    if message:

        # Meta echoes messages sent by the Instagram account back to the
        # webhook. Do not save them as inbound messages or auto-reply to them.
        if message.get("is_echo"):
            print("🔁 INSTAGRAM OUTBOUND ECHO IGNORED")
            return empty_normalized_message(
                channel="instagram",
                payload=payload,
            )

        attachment = (
            extract_attachment(
                message
            )
        )

        result = {
            "channel":
                "instagram",

            "external_user_id":
                event.get(
                    "sender",
                    {},
                ).get(
                    "id"
                ),

            "external_message_id":
                message.get(
                    "mid"
                ),

            "content":
                message.get(
                    "text"
                ),

            "media_type":
                attachment.get(
                    "media_type"
                ),

            "media_url":
                attachment.get(
                    "media_url"
                ),

            "raw_payload":
                payload,
        }


        print(
            "📥 INSTAGRAM NORMALIZED MESSAGE | "
            f"content={result.get('content')!r} | "
            f"media_type={result.get('media_type')!r} | "
            f"media_url={result.get('media_url')!r}"
        )


        return result


    # =====================================================
    # CASE 2:
    # MESSAGE_EDIT
    # =====================================================

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

        access_token = get_meta_config()["facebook_page_access_token"]


        print(
            "[INFO] Instagram đang sử dụng "
            "FACEBOOK_PAGE_ACCESS_TOKEN"
        )


        result = (
            fetch_instagram_message_data(
                mid=mid,
                access_token=access_token,
            )
        )


        sender_id = (
            result.get(
                "sender_id"
            )
            or event.get(
                "sender",
                {},
            ).get(
                "id"
            )
        )


        content = result.get(
            "content"
        )

        media_type = result.get(
            "media_type"
        )

        media_url = result.get(
            "media_url"
        )


        print(
            "[INFO] "
            "message_edit(num_edit=0) | "
            f"content={content!r} | "
            f"sender_id={sender_id!r} | "
            f"media_type={media_type!r} | "
            f"media_url={media_url!r}"
        )


        return {
            "channel":
                "instagram",

            "external_user_id":
                sender_id,

            "external_message_id":
                mid,

            "content":
                content,

            "media_type":
                media_type,

            "media_url":
                media_url,

            "raw_payload":
                payload,
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

    channel = message.get(
        "channel"
    )

    external_user_id = message.get(
        "external_user_id"
    )

    external_message_id = message.get(
        "external_message_id"
    )


    # =====================================================
    # 0. INSTAGRAM OUTBOUND ECHO
    # =====================================================

    if channel == "instagram":

        instagram_account_id = str(
            get_meta_config()["instagram_account_id"] or ""
        ).strip()

        sender_id = (
            str(
                external_user_id
            ).strip()
            if external_user_id is not None
            else ""
        )

        if (
            instagram_account_id
            and sender_id
            == instagram_account_id
        ):

            print(
                "🔁 INSTAGRAM OUTBOUND "
                "ECHO IGNORED | "
                f"sender_id={sender_id}"
            )

            return False


    # =====================================================
    # 1. VALIDATE
    # =====================================================

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


    # =====================================================
    # 2. TÌM CUSTOMER
    # =====================================================

    customer = db.execute(
        text("""
            SELECT
                id,
                name,
                avatar_url

            FROM customers

            WHERE channel = :channel
              AND external_user_id = :external_user_id

            LIMIT 1
        """),
        {
            "channel":
                channel,

            "external_user_id":
                external_user_id,
        },
    ).first()


    # =====================================================
    # 3. PROFILE
    # =====================================================

    customer_name = None
    avatar_url = None


    should_fetch_profile = (
        customer is None
        or not customer.name
        or not customer.avatar_url
    )


    # =====================================================
    # FACEBOOK PROFILE
    # =====================================================

    if (
        channel == "facebook"
        and should_fetch_profile
    ):

        profile = (
            fetch_facebook_customer_profile(
                str(
                    external_user_id
                )
            )
        )

        customer_name = profile.get(
            "name"
        )

        avatar_url = profile.get(
            "avatar_url"
        )


    # =====================================================
    # INSTAGRAM PROFILE
    # =====================================================

    elif (
        channel == "instagram"
        and should_fetch_profile
    ):

        profile = (
            fetch_instagram_customer_profile(
                str(
                    external_user_id
                )
            )
        )

        customer_name = profile.get(
            "name"
        )

        avatar_url = profile.get(
            "avatar_url"
        )


    # =====================================================
    # 4. CREATE CUSTOMER
    # =====================================================

    if customer is None:

        customer = db.execute(
            text("""
                INSERT INTO customers (
                    channel,
                    external_user_id,
                    name,
                    avatar_url
                )
                VALUES (
                    :channel,
                    :external_user_id,
                    :name,
                    :avatar_url
                )
                RETURNING
                    id,
                    name,
                    avatar_url
            """),
            {
                "channel":
                    channel,

                "external_user_id":
                    external_user_id,

                "name":
                    customer_name,

                "avatar_url":
                    avatar_url,
            },
        ).first()


        db.commit()


        print(
            "✅ CREATED CUSTOMER | "
            f"id={customer.id} | "
            f"name={customer.name!r}"
        )


    # =====================================================
    # 5. UPDATE CUSTOMER PROFILE
    # =====================================================

    elif (
        channel in (
            "facebook",
            "instagram",
        )
        and (
            customer_name
            or avatar_url
        )
    ):

        db.execute(
            text("""
                UPDATE customers

                SET
                    name = COALESCE(
                        :name,
                        name
                    ),

                    avatar_url = COALESCE(
                        :avatar_url,
                        avatar_url
                    )

                WHERE id = :customer_id
            """),
            {
                "name":
                    customer_name,

                "avatar_url":
                    avatar_url,

                "customer_id":
                    customer.id,
            },
        )


        db.commit()


        print(
            "✅ UPDATED CUSTOMER PROFILE | "
            f"channel={channel} | "
            f"customer_id={customer.id} | "
            f"name={customer_name!r}"
        )


    customer_id = (
        customer.id
    )


    # =====================================================
    # 6. TÌM CONVERSATION
    # =====================================================

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
            "customer_id":
                customer_id,

            "channel":
                channel,
        },
    ).first()


    # =====================================================
    # 7. CREATE CONVERSATION
    # =====================================================

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
                "customer_id":
                    customer_id,

                "channel":
                    channel,
            },
        ).first()


        db.commit()


        print(
            "✅ CREATED CONVERSATION | "
            f"id={conversation.id}"
        )


    conversation_id = (
        conversation.id
    )


    # =====================================================
    # 8. MESSAGE INFO
    # =====================================================

    message[
        "conversation_id"
    ] = conversation_id


    message[
        "direction"
    ] = "inbound"


    # =====================================================
    # 9. SAVE MESSAGE
    # =====================================================

    saved_message = save_message(
        db=db,
        message=message,
    )


    print(
        "✅ MESSAGE SAVED | "
        f"customer_id={customer_id} | "
        f"conversation_id={conversation_id} | "
        f"direction=inbound | "
        f"media_type={message.get('media_type')!r} | "
        f"media_url={message.get('media_url')!r} | "
        f"external_message_id="
        f"{external_message_id}"
    )

    # RAG Auto-reply check
    if message.get("content"):
        try:
            from app.services.auto_reply_service import process_rag_auto_reply_background
            process_rag_auto_reply_background(
                conversation_id=conversation_id,
                channel=channel,
                query_text=message.get("content"),
            )
        except Exception as exc:
            print("Auto-reply trigger error:", str(exc))



    return saved_message or {
        "conversation_id":
            conversation_id,
        "channel":
            channel,
        "external_user_id":
            external_user_id,
        "external_message_id":
            external_message_id,
        "direction":
            "inbound",
        "content":
            message.get(
                "content"
            ),
        "media_type":
            message.get(
                "media_type"
            ),
        "media_url":
            message.get(
                "media_url"
            ),
        "raw_payload":
            message.get(
                "raw_payload"
            ),
    }
