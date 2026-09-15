import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError

from app.database.bases import TenantBase
from app.models.channel import Channel
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.message import Message
from app.models.crm_extended import ConversationAssignment
from app.models.customer_identity import CustomerIdentity
from app.models.message_attachment import MessageAttachment
from app.services.message_service import process_and_save_message, fetch_facebook_customer_profile, fetch_instagram_customer_profile
from app.database.tenant_session import tenant_session
from app.services.channel_service import upsert_channel_connection
from cryptography.fernet import Fernet


class TenantScopedQueryTests(unittest.TestCase):
    def test_profile_enrichment_in_production_never_uses_global_default_credentials(self):
        with patch("app.services.message_service.settings.ENVIRONMENT", "production"):
            with patch("app.services.message_service.get_meta_config", side_effect=AssertionError("Global credentials accessed")):
                self.assertIsNone(fetch_facebook_customer_profile("person")["name"])
                self.assertIsNone(fetch_instagram_customer_profile("person")["name"])

    def test_channel_connection_repository_never_needs_platform_tables(self):
        engine = create_engine("sqlite://")
        reserved_slots = []
        try:
            TenantBase.metadata.create_all(engine)
            with Session(engine) as db:
                channel = upsert_channel_connection(
                    db, business_id=1, channel_type="facebook", external_account_id="page",
                    name="Shop page", access_token="secret", encryption_key=Fernet.generate_key().decode(),
                    reserve_channel_slot=lambda: reserved_slots.append("reserved"),
                )
                self.assertEqual("Shop page", db.get(Channel, channel.id).name)
                self.assertIsNone(channel.access_token)
                self.assertEqual(["reserved"], reserved_slots)
        finally:
            engine.dispose()

    def test_channel_connection_requires_platform_quota_reservation_before_new_slot(self):
        engine = create_engine("sqlite://")
        try:
            TenantBase.metadata.create_all(engine)
            with Session(engine) as db:
                with self.assertRaises(RuntimeError):
                    upsert_channel_connection(
                        db, business_id=1, channel_type="facebook", external_account_id="page",
                        name="Shop page", access_token="secret",
                    )
                self.assertEqual(0, db.query(Channel).count())
        finally:
            engine.dispose()

    def test_schema_routing_is_reapplied_after_service_commits(self):
        engine = create_engine("sqlite://")
        routed_paths = []

        @event.listens_for(engine, "connect")
        def add_set_config(connection, _record):
            connection.create_function("set_config", 3, lambda _name, value, _local: routed_paths.append(value) or value)

        try:
            with patch("app.database.tenant_session.TenantSessionLocal", sessionmaker(bind=engine)):
                with tenant_session("shop_1") as db:
                    db.execute(text("SELECT 1"))
                    db.commit()
                    db.execute(text("SELECT 2"))
                    db.commit()
            self.assertEqual(['"shop_1", public', '"shop_1", public'], routed_paths)
        finally:
            engine.dispose()

    def test_inbound_message_without_resolved_business_never_queries_platform_tables(self):
        engine = create_engine("sqlite://")
        try:
            with Session(engine) as db:
                self.assertFalse(process_and_save_message(db, {
                    "channel": "facebook", "external_user_id": "person", "external_message_id": "message",
                }))
        finally:
            engine.dispose()

    def test_inbound_message_business_must_match_bound_session(self):
        engine = create_engine("sqlite://")
        try:
            with Session(engine) as db:
                db.info["business_id"] = 1
                self.assertFalse(process_and_save_message(db, {
                    "business_id": 2, "channel": "facebook", "external_user_id": "person", "external_message_id": "message",
                }))
        finally:
            engine.dispose()

    def test_core_crm_models_belong_to_tenant_metadata_without_platform_foreign_keys(self):
        for model in (Customer, Conversation, Message, Channel, ConversationAssignment, CustomerIdentity, MessageAttachment):
            self.assertIs(TenantBase.metadata, model.metadata)
            self.assertFalse(
                any(
                    foreign_key.target_fullname.startswith(("businesses.", "users."))
                    for column in model.__table__.columns
                    for foreign_key in column.foreign_keys
                ),
                f"{model.__name__} retains a platform foreign key",
            )

    def test_tenant_metadata_can_create_without_any_platform_tables(self):
        engine = create_engine("sqlite://")
        try:
            TenantBase.metadata.create_all(engine)
            self.assertNotIn("businesses", TenantBase.metadata.tables)
            self.assertNotIn("users", TenantBase.metadata.tables)
            for table in TenantBase.metadata.tables.values():
                for foreign_key in table.foreign_keys:
                    self.assertIs(TenantBase.metadata, foreign_key.column.table.metadata)
        finally:
            engine.dispose()

    def test_channel_account_uniqueness_is_local_even_if_audit_business_id_differs(self):
        engine = create_engine("sqlite://")
        try:
            TenantBase.metadata.create_all(engine)
            with Session(engine) as db:
                db.add(Channel(business_id=1, channel_type="facebook", name="Page", external_account_id="same-page"))
                db.commit()
                db.add(Channel(business_id=2, channel_type="facebook", name="Duplicate", external_account_id="same-page"))
                with self.assertRaises(IntegrityError):
                    db.commit()
        finally:
            engine.dispose()

    def test_identical_channel_account_and_message_ids_are_isolated_by_session(self):
        first_engine = create_engine("sqlite://")
        second_engine = create_engine("sqlite://")
        try:
            for business_id, engine in ((1, first_engine), (2, second_engine)):
                TenantBase.metadata.create_all(engine)
                with Session(engine) as db:
                    customer = Customer(
                        id=1, business_id=business_id, channel="facebook",
                        external_user_id="same-person",
                    )
                    channel = Channel(
                        id=1, business_id=business_id, channel_type="facebook",
                        name="Same provider account", external_account_id="same-page",
                    )
                    conversation = Conversation(
                        id=1, business_id=business_id, customer_id=customer.id,
                        channel_id=channel.id, channel="facebook",
                    )
                    message = Message(
                        id=1, conversation_id=conversation.id, channel="facebook",
                        external_message_id="same-message", content=f"shop-{business_id}",
                    )
                    db.add_all((customer, channel, conversation, message))
                    db.commit()

            with Session(first_engine) as first, Session(second_engine) as second:
                self.assertEqual("shop-1", first.get(Message, 1).content)
                self.assertEqual("shop-2", second.get(Message, 1).content)
        finally:
            first_engine.dispose()
            second_engine.dispose()


if __name__ == "__main__":
    unittest.main()
