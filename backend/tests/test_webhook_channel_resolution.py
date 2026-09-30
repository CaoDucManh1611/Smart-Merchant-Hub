import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Business, Channel
from app.tenancy.webhook import resolve_channel_business, resolve_telegram_channel, resolve_zalo_channel
from app.services.channel_credentials import encrypt_token
from app.core.config import settings


class WebhookChannelResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Webhook Shop", slug="webhook-shop")
            db.add(business)
            db.flush()
            db.add(Channel(
                business_id=business.id,
                channel_type="facebook",
                name="Shop Page",
                external_account_id="page-123",
                status="active",
            ))
            db.commit()
            cls.business_id = business.id

    def test_resolves_active_channel_to_its_business(self):
        with Session(self.engine) as db:
            self.assertEqual(
                self.business_id,
                resolve_channel_business(db, "facebook", "page-123"),
            )

    def test_does_not_resolve_unknown_or_inactive_channel(self):
        with Session(self.engine) as db:
            self.assertIsNone(resolve_channel_business(db, "facebook", "unknown"))

    def test_bot_webhook_resolvers_accept_encrypted_channel_secrets(self):
        settings.CHANNEL_ENCRYPTION_KEY = "webhook-resolution-test-key"
        with Session(self.engine) as db:
            telegram = Channel(
                business_id=self.business_id,
                channel_type="telegram",
                name="Telegram Bot",
                external_account_id="telegram-123",
                status="active",
                config={"webhook_secret_encrypted": encrypt_token("telegram-secret", settings.CHANNEL_ENCRYPTION_KEY)},
            )
            zalo = Channel(
                business_id=self.business_id,
                channel_type="zalo",
                name="Zalo Bot",
                external_account_id="zalo-123",
                status="active",
                config={"webhook_secret_encrypted": encrypt_token("zalo-secret", settings.CHANNEL_ENCRYPTION_KEY)},
            )
            db.add_all([telegram, zalo])
            db.commit()
            self.assertEqual(telegram.id, resolve_telegram_channel(db, "telegram-secret").id)
            self.assertEqual(zalo.id, resolve_zalo_channel(db, "zalo-secret").id)


if __name__ == "__main__":
    unittest.main()
