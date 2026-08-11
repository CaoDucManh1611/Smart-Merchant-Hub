import json

from sqlalchemy import text


def save_message(
    db,
    message: dict,
):
    """
    Lưu message vào PostgreSQL.
    """

    query = text("""
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
    """)

    db.execute(
        query,
        {
            "conversation_id":
                message.get("conversation_id"),

            "channel":
                message.get("channel"),

            "external_user_id":
                message.get("external_user_id"),

            "external_message_id":
                message.get("external_message_id"),

            "direction":
                message.get(
                    "direction",
                    "inbound",
                ),

            "content":
                message.get("content"),

            "raw_payload":
                json.dumps(
                    message.get("raw_payload")
                ),
        },
    )

    db.commit()