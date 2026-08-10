from sqlalchemy import text


def save_message(db, message: dict):
    query = text("""
        INSERT INTO messages (
            channel,
            external_user_id,
            external_message_id,
            content,
            sent_at,
            raw_payload
        )
        VALUES (
            :channel,
            :external_user_id,
            :external_message_id,
            :content,
            :sent_at,
            CAST(:raw_payload AS JSONB)
        )
        ON CONFLICT (external_message_id) DO NOTHING
    """)

    db.execute(
        query,
        {
            "channel": message.get("channel"),
            "external_user_id": message.get("external_user_id"),
            "external_message_id": message.get("external_message_id"),
            "content": message.get("content"),
            "sent_at": message.get("sent_at"),
            "raw_payload": __import__("json").dumps(
                message.get("raw_payload")
            ),
        },
    )

    db.commit()