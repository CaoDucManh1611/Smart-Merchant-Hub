import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.services.channel_credentials import decrypt_token, encrypt_token
from app.models.business import Business
from app.models.channel import Channel
from app.services.channel_service import upsert_channel_connection
from app.core.config import settings
from app.tenancy.oauth import consume_oauth_state, issue_oauth_state, register_oauth_state, verify_oauth_state


class ChannelCredentialTests(unittest.TestCase):
    def test_token_is_encrypted_and_round_trips(self):
        encrypted = encrypt_token("secret-token", "test-key")
        self.assertNotEqual("secret-token", encrypted)
        self.assertEqual("secret-token", decrypt_token(encrypted, "test-key"))

    def test_oauth_state_is_single_use(self):
        engine = create_engine("sqlite://")
        Business.metadata.create_all(engine)
        with Session(engine) as db:
            business = Business(name="OAuth", slug="oauth")
            db.add(business)
            db.commit()
            state = issue_oauth_state(business.id, "test-key")
            register_oauth_state(db, state, "test-key")
            self.assertEqual(business.id, verify_oauth_state(state, "test-key")["business_id"])
            self.assertTrue(consume_oauth_state(db, state, "test-key"))
            with self.assertRaises(PermissionError):
                consume_oauth_state(db, state, "test-key")

    def test_external_account_cannot_be_claimed_by_another_business(self):
        settings.CHANNEL_ENCRYPTION_KEY = "test-key"
        engine = create_engine("sqlite://")
        Business.metadata.create_all(engine)
        with Session(engine) as db:
            first = Business(name="One", slug="one")
            second = Business(name="Two", slug="two")
            db.add_all([first, second])
            db.commit()
            upsert_channel_connection(
                db,
                business_id=first.id,
                channel_type="facebook",
                external_account_id="page-1",
                name="Page",
                access_token="token",
            )
            with self.assertRaises(PermissionError):
                upsert_channel_connection(
                    db,
                    business_id=second.id,
                    channel_type="facebook",
                    external_account_id="page-1",
                    name="Page",
                    access_token="token-2",
                )


if __name__ == "__main__":
    unittest.main()
