import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Business, Channel, Conversation, Customer, Message, MessageAttachment
from app.services.media_service import save_message_attachments
from app.services.message_service import process_and_save_message
from app.contracts.channel_event import MediaType, NormalizedAttachment


class MediaPersistenceTests(unittest.TestCase):
    def test_saves_all_attachments_and_is_idempotent(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        # The helper only touches the attachment table; create its parents as
        # lightweight tables so SQLite can enforce foreign keys when enabled.
        Business.metadata.create_all(engine)
        with Session(engine) as db:
            business = Business(name="Media Shop", slug="media-shop")
            db.add(business)
            db.flush()
            channel = Channel(
                business_id=business.id,
                channel_type="telegram",
                name="Telegram",
                external_account_id="bot-1",
            )
            db.add(channel)
            db.flush()
            customer = Customer(
                business_id=business.id,
                channel="telegram",
                external_user_id="user-1",
            )
            db.add(customer)
            db.flush()
            conversation = Conversation(
                business_id=business.id,
                customer_id=customer.id,
                channel_id=channel.id,
                channel="telegram",
            )
            db.add(conversation)
            db.flush()
            message = Message(
                conversation_id=conversation.id,
                channel="telegram",
                external_user_id="user-1",
                external_message_id="telegram:1:1",
                direction="inbound",
            )
            db.add(message)
            db.flush()
            db.commit()

            attachments = [
                NormalizedAttachment(
                    media_type=MediaType.IMAGE,
                    external_attachment_id="photo-1",
                    metadata={"mime_type": "image/jpeg"},
                ),
                NormalizedAttachment(
                    media_type=MediaType.AUDIO,
                    external_attachment_id="voice-1",
                    metadata={"duration": 3},
                ),
            ]
            rows = save_message_attachments(
                db,
                message_id=message.id,
                business_id=business.id,
                channel_id=channel.id,
                attachments=attachments,
            )
            db.commit()
            self.assertEqual(["image", "audio"], [row.media_type for row in rows])
            again = save_message_attachments(
                db,
                message_id=message.id,
                business_id=business.id,
                channel_id=channel.id,
                attachments=attachments,
            )
            db.commit()
            self.assertEqual(2, len(db.scalars(select(MessageAttachment)).all()))
            self.assertEqual([row.id for row in rows], [row.id for row in again])

            # Telegram file_id is reusable across messages. It must be
            # idempotent per message, not globally unique for the channel.
            second_message = Message(
                conversation_id=conversation.id,
                channel="telegram",
                external_user_id="user-1",
                external_message_id="telegram:1:2",
                direction="inbound",
            )
            db.add(second_message)
            db.flush()
            second_rows = save_message_attachments(
                db,
                message_id=second_message.id,
                business_id=business.id,
                channel_id=channel.id,
                attachments=[attachments[0]],
            )
            db.commit()
            self.assertEqual(1, len(second_rows))
            self.assertEqual(3, len(db.scalars(select(MessageAttachment)).all()))

    def test_inbound_saved_payload_exposes_proxy_url_for_realtime_clients(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(engine)
        with Session(engine) as db:
            business = Business(name="Realtime Media Shop", slug="realtime-media-shop")
            db.add(business)
            db.flush()
            channel = Channel(
                business_id=business.id,
                channel_type="telegram",
                name="Telegram",
                external_account_id="bot-realtime",
            )
            db.add(channel)
            db.flush()

            saved = process_and_save_message(
                db,
                {
                    "channel": "telegram",
                    "business_id": business.id,
                    "channel_id": channel.id,
                    "external_account_id": channel.external_account_id,
                    "external_user_id": "user-realtime",
                    "external_message_id": "telegram:realtime:1",
                    "content": None,
                    "media_type": "audio",
                    "media_url": None,
                    "attachments": [
                        NormalizedAttachment(
                            media_type=MediaType.AUDIO,
                            external_attachment_id="voice-realtime",
                        )
                    ],
                    "raw_payload": {"message": {"voice": {"file_id": "voice-realtime"}}},
                },
            )

        media_url = saved["attachments"][0]["media_url"]
        self.assertTrue(media_url.startswith("/api/media/1?"))
        self.assertIn("business_id=1", media_url)
        self.assertIn("signature=", media_url)


if __name__ == "__main__":
    unittest.main()
