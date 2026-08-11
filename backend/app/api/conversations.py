import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.services.facebook_service import send_facebook_message
from app.services.instagram_service import send_instagram_message


router = APIRouter()


# =========================================================
# SCHEMA
# =========================================================

class SendMessageRequest(BaseModel):
    text: str


# =========================================================
# GET CONVERSATIONS
# =========================================================

@router.get("")
def get_conversations(
    db: Session = Depends(get_db),
):
    """
    Lấy danh sách conversation,
    kèm thông tin customer và message mới nhất.
    """

    query = text("""
        SELECT
            cv.id AS conversation_id,
            cv.customer_id,
            c.external_user_id,
            c.name AS customer_name,
            cv.channel,
            cv.status,
            cv.created_at,
            cv.updated_at,

            (
                SELECT m.content
                FROM messages m
                WHERE m.conversation_id = cv.id
                ORDER BY m.id DESC
                LIMIT 1
            ) AS last_message,

            (
                SELECT m.direction
                FROM messages m
                WHERE m.conversation_id = cv.id
                ORDER BY m.id DESC
                LIMIT 1
            ) AS last_message_direction,

            (
                SELECT m.received_at
                FROM messages m
                WHERE m.conversation_id = cv.id
                ORDER BY m.id DESC
                LIMIT 1
            ) AS last_message_at

        FROM conversations cv

        JOIN customers c
            ON c.id = cv.customer_id

        ORDER BY last_message_at DESC NULLS LAST
    """)

    result = db.execute(
        query
    ).mappings().all()

    return {
        "items": [
            dict(row)
            for row in result
        ]
    }


# =========================================================
# GET MESSAGES OF CONVERSATION
# =========================================================

@router.get("/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
):
    """
    Lấy toàn bộ message
    của một conversation.
    """

    query = text("""
        SELECT
            m.id AS message_id,
            m.conversation_id,
            m.channel,
            m.external_user_id,
            m.external_message_id,
            m.direction,
            m.content,
            m.raw_payload,
            m.received_at

        FROM messages m

        WHERE m.conversation_id = :conversation_id

        ORDER BY m.id ASC
    """)

    result = db.execute(
        query,
        {
            "conversation_id": conversation_id,
        },
    ).mappings().all()

    return {
        "conversation_id": conversation_id,
        "items": [
            dict(row)
            for row in result
        ],
    }


# =========================================================
# SEND MESSAGE
# =========================================================

@router.post("/{conversation_id}/messages")
def send_message(
    conversation_id: int,
    body: SendMessageRequest,
    db: Session = Depends(get_db),
):
    """
    Gửi tin nhắn từ CRM tới khách hàng.

    Hỗ trợ:
    - Facebook
    - Instagram
    """

    # ==========================================
    # 1. TÌM CONVERSATION
    # ==========================================

    conversation = db.execute(
        text("""
            SELECT
                cv.id,
                cv.channel,
                cv.customer_id,
                c.external_user_id

            FROM conversations cv

            JOIN customers c
                ON c.id = cv.customer_id

            WHERE cv.id = :conversation_id
        """),
        {
            "conversation_id": conversation_id,
        },
    ).mappings().first()

    # ==========================================
    # 2. KHÔNG TÌM THẤY CONVERSATION
    # ==========================================

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    channel = conversation["channel"]

    recipient_id = conversation[
        "external_user_id"
    ]

    # ==========================================
    # 3. FACEBOOK
    # ==========================================

    if channel == "facebook":

        try:

            result = send_facebook_message(
                recipient_id=recipient_id,
                text=body.text,
            )

            external_message_id = result.get(
                "message_id"
            )

            db.execute(
                text("""
                    INSERT INTO messages (
                        conversation_id,
                        channel,
                        external_user_id,
                        external_message_id,
                        direction,
                        content,
                        raw_payload
                    )
                    VALUES (
                        :conversation_id,
                        :channel,
                        :external_user_id,
                        :external_message_id,
                        :direction,
                        :content,
                        CAST(:raw_payload AS JSONB)
                    )
                    ON CONFLICT (
                        external_message_id
                    )
                    DO NOTHING
                """),
                {
                    "conversation_id":
                        conversation_id,

                    "channel":
                        "facebook",

                    "external_user_id":
                        recipient_id,

                    "external_message_id":
                        external_message_id,

                    "direction":
                        "outbound",

                    "content":
                        body.text,

                    "raw_payload":
                        json.dumps(
                            {
                                "direction":
                                    "outbound",

                                "meta_response":
                                    result,
                            }
                        ),
                },
            )

            db.commit()

            print(
                "✅ OUTBOUND FACEBOOK "
                "MESSAGE SAVED | "
                f"conversation_id="
                f"{conversation_id} | "
                f"external_message_id="
                f"{external_message_id}"
            )

            return {
                "status": "sent",
                "channel": "facebook",
                "direction": "outbound",
                "conversation_id":
                    conversation_id,
                "external_message_id":
                    external_message_id,
                "result": result,
            }

        except Exception as e:

            db.rollback()

            print(
                "❌ FACEBOOK SEND ERROR:",
                str(e),
            )

            raise HTTPException(
                status_code=500,
                detail=(
                    "Không thể gửi "
                    "Facebook message"
                ),
            )

    # ==========================================
    # 4. INSTAGRAM
    # ==========================================

    if channel == "instagram":

        try:

            result = send_instagram_message(
                recipient_id=recipient_id,
                text=body.text,
            )

            external_message_id = result.get(
                "message_id"
            )

            db.execute(
                text("""
                    INSERT INTO messages (
                        conversation_id,
                        channel,
                        external_user_id,
                        external_message_id,
                        direction,
                        content,
                        raw_payload
                    )
                    VALUES (
                        :conversation_id,
                        :channel,
                        :external_user_id,
                        :external_message_id,
                        :direction,
                        :content,
                        CAST(:raw_payload AS JSONB)
                    )
                    ON CONFLICT (
                        external_message_id
                    )
                    DO NOTHING
                """),
                {
                    "conversation_id":
                        conversation_id,

                    "channel":
                        "instagram",

                    "external_user_id":
                        recipient_id,

                    "external_message_id":
                        external_message_id,

                    "direction":
                        "outbound",

                    "content":
                        body.text,

                    "raw_payload":
                        json.dumps(
                            {
                                "direction":
                                    "outbound",

                                "meta_response":
                                    result,
                            }
                        ),
                },
            )

            db.commit()

            print(
                "✅ OUTBOUND INSTAGRAM "
                "MESSAGE SAVED | "
                f"conversation_id="
                f"{conversation_id} | "
                f"external_message_id="
                f"{external_message_id}"
            )

            return {
                "status": "sent",
                "channel": "instagram",
                "direction": "outbound",
                "conversation_id":
                    conversation_id,
                "external_message_id":
                    external_message_id,
                "result": result,
            }

        except Exception as e:

            db.rollback()

            print(
                "❌ INSTAGRAM SEND ERROR:",
                str(e),
            )

            raise HTTPException(
                status_code=500,
                detail=(
                    "Không thể gửi "
                    "Instagram message"
                ),
            )

    # ==========================================
    # 5. CHANNEL KHÁC
    # ==========================================

    raise HTTPException(
        status_code=400,
        detail=(
            "Send message chưa hỗ trợ "
            f"channel: {channel}"
        ),
    )