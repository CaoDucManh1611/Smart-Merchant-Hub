import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.conversation import Conversation
from app.models.business import Business
from app.models.customer import Customer
from app.models.customer_identity import CustomerIdentity
from app.models.message import Message
from app.services.customer_identity import resolve_conversation_recipient, resolve_customer


class CustomerIdentityResolutionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Business.metadata.create_all(self.engine)

    def test_same_platform_identity_is_reused(self):
        with Session(self.engine) as db:
            business = Business(name="Shop", slug="shop")
            db.add(business)
            db.commit()

            first = resolve_customer(
                db,
                business_id=business.id,
                channel="facebook",
                external_user_id="fb-1",
                external_account_id="page-1",
                name="Nguyen A",
            )
            second = resolve_customer(
                db,
                business_id=business.id,
                channel="facebook",
                external_user_id="fb-1",
                external_account_id="page-1",
            )

            self.assertEqual(first.id, second.id)
            self.assertEqual(1, len(db.scalars(select(Customer)).all()))
            self.assertEqual(1, len(db.scalars(select(CustomerIdentity)).all()))

    def test_verified_phone_links_a_new_channel_to_existing_customer(self):
        with Session(self.engine) as db:
            business = Business(name="Shop", slug="shop")
            db.add(business)
            db.commit()

            first = resolve_customer(
                db,
                business_id=business.id,
                channel="facebook",
                external_user_id="fb-1",
                external_account_id="page-1",
                phone="+84901234567",
            )
            second = resolve_customer(
                db,
                business_id=business.id,
                channel="telegram",
                external_user_id="tg-1",
                external_account_id="bot-1",
                phone="+84901234567",
            )

            self.assertEqual(first.id, second.id)
            self.assertEqual(2, len(db.scalars(select(CustomerIdentity)).all()))

    def test_lower_priority_name_cannot_replace_a_stored_display_name(self):
        with Session(self.engine) as db:
            business = Business(name="Shop", slug="shop")
            db.add(business)
            db.commit()

            customer = resolve_customer(
                db,
                business_id=business.id,
                channel="instagram",
                external_user_id="ig-1",
                external_account_id="ig-account-1",
                display_name="Tên hiển thị đáng tin cậy",
            )
            refreshed = resolve_customer(
                db,
                business_id=business.id,
                channel="instagram",
                external_user_id="ig-1",
                external_account_id="ig-account-1",
                name="Tên từ nguồn thấp hơn",
            )

            self.assertEqual(customer.id, refreshed.id)
            self.assertEqual("Tên hiển thị đáng tin cậy", refreshed.name)

    def test_same_external_id_in_another_business_is_isolated(self):
        with Session(self.engine) as db:
            first_business = Business(name="One", slug="one")
            second_business = Business(name="Two", slug="two")
            db.add_all([first_business, second_business])
            db.commit()

            first = resolve_customer(db, first_business.id, "facebook", "same", "page-1")
            second = resolve_customer(db, second_business.id, "facebook", "same", "page-1")

            self.assertNotEqual(first.id, second.id)

    def _merged_telegram_conversation(self, db, *, chat_id, sender_id):
        business = Business(name="Shop", slug="shop")
        db.add(business)
        db.commit()
        customer = Customer(
            business_id=business.id,
            channel="facebook",
            external_user_id="facebook-customer-1",
        )
        channel = Channel(
            business_id=business.id,
            channel_type="telegram",
            name="Telegram bot",
            external_account_id="telegram-bot-1",
            status="active",
        )
        db.add_all([customer, channel])
        db.commit()
        db.add(CustomerIdentity(
            business_id=business.id,
            customer_id=customer.id,
            channel="telegram",
            external_account_id=channel.external_account_id,
            external_user_id=sender_id,
        ))
        conversation = Conversation(
            business_id=business.id,
            customer_id=customer.id,
            channel_id=channel.id,
            channel="telegram",
        )
        db.add(conversation)
        db.commit()
        db.add(Message(
            conversation_id=conversation.id,
            channel="telegram",
            external_user_id=sender_id,
            direction="inbound",
            content="hello",
            raw_payload={"message": {"chat": {"id": chat_id, "type": "private"}}},
        ))
        db.commit()
        return business, conversation

    def test_telegram_recipient_uses_channel_chat_not_merged_primary_customer(self):
        with Session(self.engine) as db:
            business, conversation = self._merged_telegram_conversation(
                db, chat_id=42001, sender_id=42001,
            )

            recipient = resolve_conversation_recipient(
                db,
                conversation_id=conversation.id,
                business_id=business.id,
            )

            self.assertEqual(("telegram", "42001"), recipient)

            from app.api.conversations import get_conversation_target
            from app.services.auto_reply_service import _get_conversation_recipient

            self.assertEqual(
                ("telegram", "42001"),
                _get_conversation_recipient(db, conversation.id, business.id),
            )
            self.assertEqual(
                "42001",
                get_conversation_target(db, conversation.id, business.id)["external_user_id"],
            )

    def test_telegram_group_reply_uses_chat_id_instead_of_sender_id(self):
        with Session(self.engine) as db:
            business, conversation = self._merged_telegram_conversation(
                db, chat_id=-10042001, sender_id=42001,
            )

            recipient = resolve_conversation_recipient(
                db,
                conversation_id=conversation.id,
                business_id=business.id,
            )

            self.assertEqual(("telegram", "-10042001"), recipient)


if __name__ == "__main__":
    unittest.main()
