import json

from sqlalchemy import text


def save_message(
    db,
    message: dict,
):
    """
    Lưu message vào PostgreSQL.

    Hỗ trợ:
    - text
    - image
    - video
    - attachment
    """

    query = text("""
        INSERT INTO messages (
            conversation_id,
            channel,
            external_user_id,
            external_message_id,
            sender_type,
            direction,
            content,
            media_type,
            media_url,
            raw_payload
        )
        VALUES (
            :conversation_id,
            :channel,
            :external_user_id,
            :external_message_id,
            :sender_type,
            :direction,
            :content,
            :media_type,
            :media_url,
            CAST(:raw_payload AS JSONB)
        )
        ON CONFLICT (
            external_message_id
        )
        DO NOTHING
        RETURNING
            id AS message_id,
            conversation_id,
            channel,
            external_user_id,
            external_message_id,
            direction,
            content,
            media_type,
            media_url,
            raw_payload,
            received_at
    """)

    result = db.execute(
        query,
        {
            "conversation_id":
                message.get(
                    "conversation_id"
                ),

            "channel":
                message.get(
                    "channel"
                ),

            "external_user_id":
                message.get(
                    "external_user_id"
                ),

            "external_message_id":
                message.get(
                    "external_message_id"
                ),

            "sender_type":
                message.get(
                    "sender_type",
                    "customer",
                ),

            "direction":
                message.get(
                    "direction",
                    "inbound",
                ),

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
                json.dumps(
                    message.get(
                        "raw_payload"
                    )
                ),
        },
    )

    row = result.mappings().first()

    # Consume INSERT ... RETURNING before committing. SQLite keeps the
    # statement cursor active until it is read, which otherwise causes
    # ``cannot commit transaction - SQL statements in progress``.
    db.commit()

    if row:
        created = dict(row)
        # Internal marker used by webhook handlers to avoid broadcasting a
        # duplicate UI event when a provider redelivers an already-persisted
        # message after an interrupted request.
        created["_created"] = True
        return created

    existing = db.execute(
        text("""
            SELECT
                id AS message_id,
                conversation_id,
                channel,
                external_user_id,
                external_message_id,
                direction,
                content,
                media_type,
                media_url,
                raw_payload,
                received_at

            FROM messages

            WHERE external_message_id = :external_message_id

            LIMIT 1
        """),
        {
            "external_message_id":
                message.get(
                    "external_message_id"
                ),
        },
    ).mappings().first()

    if existing:
        duplicate = dict(existing)
        duplicate["_created"] = False
        return duplicate

    return None
