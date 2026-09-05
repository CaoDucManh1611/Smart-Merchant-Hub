import logging
from typing import Any

import httpx
from sqlalchemy import text
from app.core.config import settings
from app.contracts.channel_event import ChannelProvider
from app.integrations._meta import parse_meta_events
from app.services.customer_identity import get_existing_name_priority, resolve_customer
from app.services.audit_service import record_audit
from app.services.customer_profile import merge_profile, profile_change_metadata
from app.services.channel_service import get_single_active_channel
from app.services.channel_credentials import decrypt_token
from app.services.workflow_engine import emit_workflow_event
from sqlalchemy.orm import Session

from app.db.message_repository import save_message
from app.services.meta_config_service import get_meta_config
from app.services.media_resolver import build_media_url
from app.tenancy.context import TenantContext

logger = logging.getLogger(__name__)


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
        "attachments": [],
        "raw_payload": payload,
    }


def extract_normalized_attachments(
    payload: dict[str, Any],
    provider: ChannelProvider,
    message_id: str | None,
) -> list[dict[str, Any]]:
    """Use the canonical Meta adapter even on the legacy development path."""
    if not message_id:
        return []
    try:
        events = parse_meta_events(payload, provider)
    except Exception:
        return []
    for event in events:
        for message in event.messages:
            if message.external_message_id == str(message_id):
                return [item.model_dump(mode="json") for item in message.attachments]
    return []


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
        logger.info("Facebook outbound echo ignored")
        return empty_normalized_message(
            channel="facebook",
            payload=payload,
        )

    attachment = extract_attachment(
        message
    )
    normalized_attachments = extract_normalized_attachments(
        payload,
        ChannelProvider.FACEBOOK,
        message.get("mid"),
    )

    return {
        "channel":
            "facebook",

        "external_account_id":
            event.get("recipient", {}).get("id")
            or event.get("page_id")
            or next(iter(payload.get("entry") or []), {}).get("id"),

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

        "attachments": normalized_attachments,

        "raw_payload":
            payload,
    }


# =========================================================
# FACEBOOK - CUSTOMER PROFILE
# =========================================================

def fetch_facebook_customer_profile(
    external_user_id: str,
    access_token: str | None = None,
) -> dict[str, Any]:

    access_token = str(access_token or get_meta_config()["facebook_page_access_token"] or "").strip()

    if not access_token:

        logger.info("Facebook profile enrichment skipped: credentials unavailable")

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

        logger.info("Fetching Facebook customer profile")

        response = httpx.get(
            url,
            params=params,
            timeout=10,
        )

        logger.info("Facebook profile response status=%s", response.status_code)

        if response.status_code != 200:

            logger.warning("Facebook profile request was rejected")

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

        logger.info("Facebook customer profile received")

        return {
            "name": name,
            "avatar_url": avatar_url,
        }

    except Exception:
        logger.warning("Facebook customer profile lookup failed")

        return {
            "name": None,
            "avatar_url": None,
        }


# =========================================================
# INSTAGRAM - CUSTOMER PROFILE
# =========================================================

def fetch_instagram_customer_profile(
    external_user_id: str,
    access_token: str | None = None,
) -> dict[str, Any]:

    access_token = str(access_token or get_meta_config()["facebook_page_access_token"] or "").strip()

    if not access_token:

        logger.info("Instagram profile enrichment skipped: credentials unavailable")

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

        logger.info("Fetching Instagram customer profile")

        response = httpx.get(
            url,
            params=params,
            timeout=10,
        )

        logger.info("Instagram profile response status=%s", response.status_code)

        if response.status_code != 200:

            logger.warning("Instagram profile request was rejected")

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

        logger.info("Instagram customer profile received")

        return {
            "name":
                display_name,

            "username":
                username,

            "avatar_url":
                avatar_url,
        }

    except Exception:
        logger.warning("Instagram customer profile lookup failed")

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

        logger.info("Instagram message detail lookup skipped: credentials unavailable")

        return {
            "content": None,
            "sender_id": None,
            "media_type": None,
            "media_url": None,
        }


    if not mid:

        logger.warning("Instagram message detail lookup skipped: missing message ID")

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

        logger.info("Fetching Instagram message details")

        response = httpx.get(
            url,
            params=params,
            timeout=10,
        )

        logger.info("Instagram message detail response status=%s", response.status_code)


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


        logger.info("Instagram message media parsed: media_type=%s", media_type)


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


    except Exception:
        logger.warning("Instagram message detail lookup failed")


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
        logger.info("Instagram message edit ignored")
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
            logger.info("Instagram outbound echo ignored")
            return empty_normalized_message(
                channel="instagram",
                payload=payload,
            )

        attachment = (
            extract_attachment(
                message
            )
        )
        normalized_attachments = extract_normalized_attachments(
            payload,
            ChannelProvider.INSTAGRAM,
            message.get("mid"),
        )

        result = {
            "channel":
                "instagram",

            "external_account_id":
                event.get("recipient", {}).get("id")
                or next(iter(payload.get("entry") or []), {}).get("id"),

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

            "attachments": normalized_attachments,

            "raw_payload":
                payload,
        }


        logger.info(
            "Instagram message normalized: is_text=%s has_media=%s",
            bool(result.get("content")),
            bool(result.get("media_type")),
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


        logger.info("Fetching Instagram message-edit details")


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


        logger.info(
            "Instagram message edit normalized: is_text=%s has_media=%s",
            bool(content),
            bool(media_type),
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
    # 1. VALIDATE
    # =====================================================

    if (
        not channel
        or not external_user_id
    ):

        logger.warning("Inbound message ignored: missing channel or external user ID")

        return False


    if not external_message_id:

        logger.warning("Inbound message ignored: missing external message ID")

        return False


    # =====================================================
    # 2. TÌM CUSTOMER
    # =====================================================

    # Prefer the tenant-scoped identity resolver whenever a business is
    # available.  The development-only fallback preserves the old local demo;
    # production must never assign an unbound event to a default business.
    business_id = message.get("business_id")
    if business_id is None and settings.ENVIRONMENT.strip().lower() != "production":
        business_id = db.execute(
            text("SELECT id FROM businesses WHERE slug = 'default-business' LIMIT 1")
        ).scalar()

    # A message without a resolved tenant must never create a legacy/global
    # conversation.  In production this is a rejected webhook; keeping the
    # guard here also protects direct callers of this service.
    if business_id is None:
        logger.warning("Inbound message ignored: tenant could not be resolved")
        return False

    if business_id is not None:
        customer = resolve_customer(
            db,
            business_id=int(business_id),
            channel=channel,
            external_user_id=str(external_user_id),
            external_account_id=message.get("external_account_id"),
        )
    else:
        customer = db.execute(
            text("""
                SELECT id, name, avatar_url
                FROM customers
                WHERE channel = :channel
                  AND external_user_id = :external_user_id
                LIMIT 1
            """),
            {"channel": channel, "external_user_id": external_user_id},
        ).first()

    profile_access_token = None
    if business_id is not None and channel in {"facebook", "instagram"}:
        try:
            channel_row = get_single_active_channel(db, int(business_id), "facebook" if channel == "instagram" else channel)
            if channel_row.access_token_encrypted:
                profile_access_token = decrypt_token(
                    channel_row.access_token_encrypted,
                    settings.CHANNEL_ENCRYPTION_KEY,
                )
        except (LookupError, ValueError):
            # Development can still use its explicitly configured fallback;
            # production simply skips profile enrichment until the encrypted
            # tenant channel is connected.
            profile_access_token = None


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
                ),
                access_token=profile_access_token,
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
                ),
                access_token=profile_access_token,
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


        logger.info("Customer record created from inbound message")


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

        changes = merge_profile(
            customer,
            existing_name_priority=get_existing_name_priority(db, customer),
            name=customer_name,
            avatar_url=avatar_url,
        )
        if changes and business_id is not None:
            record_audit(
                db,
                business_id=int(business_id),
                action="profile_update",
                resource_type="customer",
                resource_id=customer.id,
                metadata=profile_change_metadata(changes),
            )
        db.commit()


        logger.info("Customer profile enriched from an inbound message")


    customer_id = (
        customer.id
    )


    # =====================================================
    # 6. TÌM CONVERSATION
    # =====================================================

    # Conversations are tenant-owned resources.  The webhook has already
    # resolved ``business_id`` from the trusted Channel record above; carry
    # that value into both the lookup and insert so a customer/account from
    # another tenant can never be reused accidentally.
    conversation = db.execute(
        text("""
            SELECT id

            FROM conversations

            WHERE customer_id = :customer_id
              AND channel = :channel
              AND business_id = :business_id
              AND status = 'open'

            ORDER BY id DESC

            LIMIT 1
        """),
        {
            "customer_id":
                customer_id,

            "channel":
                channel,

            "business_id":
                int(business_id),
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
                    business_id,
                    channel_id,
                    channel,
                    status
                )
                VALUES (
                    :customer_id,
                    :business_id,
                    :channel_id,
                    :channel,
                    'open'
                )
                RETURNING id
            """),
            {
                "customer_id":
                    customer_id,

                "business_id":
                    int(business_id),

                "channel_id":
                    message.get("channel_id"),

                "channel":
                    channel,
            },
        ).first()


        db.commit()


        logger.info("Conversation created from inbound message")


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

    # Keep the legacy media columns as a compatibility mirror while storing
    # the complete canonical attachment list in the tenant-owned table.
    persisted_attachments = []
    if saved_message and message.get("attachments") and message.get("channel_id"):
        try:
            from app.services.media_service import save_message_attachments

            persisted_attachments = save_message_attachments(
                db,
                message_id=int(saved_message["message_id"]),
                business_id=int(business_id),
                channel_id=int(message["channel_id"]),
                attachments=message.get("attachments") or [],
            )
        except Exception:
            # A malformed provider attachment must not make the already
            # accepted text message disappear; keep the error visible for
            # operators and continue with the compatibility path.
            logger.warning("Message attachment persistence failed")

    # Keep the CRM list ordered by the latest interaction and make the
    # database change visible even when the message is later handled by the
    # background auto-reply worker.
    db.execute(
        text(
            """
            UPDATE conversations
            SET updated_at = CURRENT_TIMESTAMP,
                last_message_at = CURRENT_TIMESTAMP
            WHERE id = :conversation_id
            """
        ),
        {"conversation_id": conversation_id},
    )
    db.execute(
        text(
            """
            UPDATE customers
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = :customer_id
            """
        ),
        {"customer_id": customer_id},
    )
    db.commit()

    if saved_message is not None and persisted_attachments:
        saved_message["attachments"] = [
            {
                "id": row.id,
                "media_type": row.media_type,
                "mime_type": row.mime_type,
                "file_name": row.file_name,
                "duration_ms": row.duration_ms,
                "external_attachment_id": row.external_attachment_id,
                # WebSocket consumers receive this payload before their next
                # messages refresh; expose the same tenant-safe proxy URL as
                # GET /conversations/{id}/messages instead of leaving
                # provider file_ids without a browser-loadable URL.
                "media_url": build_media_url(
                    attachment_id=row.id,
                    business_id=int(business_id),
                ),
                "source_url": row.source_url,
                "storage_key": row.storage_key,
                "metadata": row.metadata_,
            }
            for row in persisted_attachments
        ]

    # Fan out the committed inbound message to enabled, tenant-scoped
    # workflows. Duplicate webhook deliveries do not emit a second event.
    if saved_message and business_id is not None:
        try:
            emit_workflow_event(
                db,
                TenantContext(int(business_id), "channel_account"),
                "message.created",
                f"message:{saved_message.get('message_id')}",
                {
                    "message_id": saved_message.get("message_id"),
                    "conversation_id": conversation_id,
                    "customer_id": customer_id,
                    "channel": channel,
                    "content": message.get("content"),
                },
            )
        except Exception:
            logger.warning("Message workflow trigger failed")


    logger.info(
        "Inbound message saved: channel=%s has_media=%s",
        channel,
        bool(message.get("media_type")),
    )

    # RAG Auto-reply check
    if message.get("content") and business_id is not None:
        if saved_message and saved_message.get("message_id"):
            try:
                from app.services.customer_fact_extractor import (
                    process_customer_fact_extraction_background,
                )

                process_customer_fact_extraction_background(
                    business_id=int(business_id),
                    customer_id=int(customer_id),
                    source_message_id=int(saved_message["message_id"]),
                    content=str(message.get("content")),
                )
            except Exception:
                logger.warning("Customer fact extraction trigger failed")
        try:
            from app.services.auto_reply_service import process_rag_auto_reply_background
            process_rag_auto_reply_background(
                conversation_id=conversation_id,
                channel=channel,
                query_text=message.get("content"),
                business_id=int(business_id),
            )
        except Exception:
            logger.warning("Auto-reply trigger failed")



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
