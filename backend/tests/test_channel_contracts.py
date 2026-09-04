import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.contracts.channel_event import (
    MessageDirection,
    NormalizedChannelEvent,
    NormalizedMessage,
    unique_channel_events,
    bind_event_to_channel,
)
from app.integrations.facebook import FacebookAdapter
from app.integrations.instagram import InstagramAdapter
from app.integrations import get_channel_adapter
from app.models.business import Business
from app.models.channel import Channel, ChannelEvent
from app.database.session import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.services.channel_event_service import ingest_normalized_events


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class ChannelContractTests(unittest.TestCase):
    def test_adapter_registry_returns_provider_adapter(self):
        self.assertIsInstance(get_channel_adapter("facebook"), FacebookAdapter)
        self.assertIsInstance(get_channel_adapter("instagram"), InstagramAdapter)

    def test_adapter_registry_rejects_unknown_provider(self):
        with self.assertRaises(ValueError):
            get_channel_adapter("email")

    def test_event_is_bound_to_resolved_channel_tenant(self):
        event = NormalizedChannelEvent(
            provider="facebook",
            external_event_id="event-tenant-1",
            event_type="message",
            external_account_id="page-1",
            raw_payload={},
        )

        bound = bind_event_to_channel(event, channel_id=42, business_id=7)

        self.assertEqual(42, bound.channel_id)
        self.assertEqual(7, bound.business_id)
        self.assertEqual("page-1", bound.external_account_id)

    def test_message_rejects_direction_outside_contract(self):
        with self.assertRaises(ValidationError):
            NormalizedMessage(
                external_message_id="message-1",
                direction="sideways",
                message_type="text",
                text="hello",
                sender_external_id="customer-1",
            )

    def test_duplicate_events_are_removed_within_same_channel_account(self):
        event = NormalizedChannelEvent(
            provider="facebook",
            external_event_id="event-1",
            event_type="message",
            external_account_id="page-1",
            sender_external_id="customer-1",
            recipient_external_id="page-1",
            raw_payload={"message": {"mid": "event-1"}},
            messages=[
                NormalizedMessage(
                    external_message_id="event-1",
                    direction=MessageDirection.INBOUND,
                    message_type="text",
                    text="hello",
                    sender_external_id="customer-1",
                )
            ],
        )

        unique = unique_channel_events([event, event.model_copy(deep=True)])

        self.assertEqual(["event-1"], [item.external_event_id for item in unique])

    def test_same_event_id_is_kept_for_different_channel_accounts(self):
        first = NormalizedChannelEvent(
            provider="facebook",
            external_event_id="event-1",
            event_type="message",
            external_account_id="page-1",
            sender_external_id="customer-1",
            recipient_external_id="page-1",
            raw_payload={},
            messages=[],
        )
        second = first.model_copy(update={"external_account_id": "page-2"})

        unique = unique_channel_events([first, second])

        self.assertEqual(2, len(unique))


class FacebookAdapterTests(unittest.TestCase):
    def test_batch_payload_returns_every_non_echo_message_from_every_entry(self):
        events = FacebookAdapter().parse_events(
            load_fixture("facebook_webhook_batch.json")
        )

        self.assertEqual(
            ["m_fb_text_001", "m_fb_image_001", "m_fb_text_002"],
            [event.external_event_id for event in events],
        )
        self.assertEqual(
            ["PAGE_001", "PAGE_001", "PAGE_002"],
            [event.external_account_id for event in events],
        )

    def test_image_attachment_is_normalized_without_losing_source_url(self):
        events = FacebookAdapter().parse_events(
            load_fixture("facebook_webhook_batch.json")
        )

        message = events[1].messages[0]
        self.assertEqual("image", message.message_type.value)
        self.assertEqual(1, len(message.attachments))
        self.assertEqual(
            "https://cdn.example.test/facebook/image-1.jpg",
            message.attachments[0].url,
        )


class InstagramAdapterTests(unittest.TestCase):
    def test_batch_payload_returns_text_and_media_messages(self):
        events = InstagramAdapter().parse_events(
            load_fixture("instagram_webhook_batch.json")
        )

        self.assertEqual(
            ["m_ig_text_001", "m_ig_media_001"],
            [event.external_event_id for event in events],
        )
        self.assertEqual("Mẫu này giá bao nhiêu?", events[0].messages[0].text)

    def test_inbox_is_idempotent_and_uses_channel_business(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            business = Business(name="Inbox", slug="inbox")
            db.add(business)
            db.commit()
            channel = Channel(business_id=business.id, channel_type="facebook", name="Page", external_account_id="page-1")
            db.add(channel)
            db.commit()
            event = NormalizedChannelEvent(provider="facebook", external_event_id="evt-1", event_type="message", external_account_id="page-1", raw_payload={})
            first = ingest_normalized_events(db, [event])
            second = ingest_normalized_events(db, [event])
            self.assertEqual(1, first[0].channel_id)
            self.assertEqual(1, first[0].business_id)
            self.assertEqual([], second)
            self.assertEqual(1, db.query(ChannelEvent).count())
    def test_all_attachments_are_preserved_in_original_order(self):
        events = InstagramAdapter().parse_events(
            load_fixture("instagram_webhook_batch.json")
        )

        message = events[1].messages[0]
        self.assertEqual("image", message.message_type.value)
        self.assertEqual(
            ["image", "video"],
            [attachment.media_type.value for attachment in message.attachments],
        )


if __name__ == "__main__":
    unittest.main()
