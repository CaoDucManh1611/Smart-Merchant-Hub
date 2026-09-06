import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Channel, Customer, CustomerIdentity
from app.services.channel_credentials import encrypt_token
from app.services import customer_avatar
from app.services.customer_avatar import (
    build_customer_avatar_url,
    verify_customer_avatar_url,
)


class CustomerAvatarUrlTests(unittest.TestCase):
    def test_build_and_verify_customer_avatar_url(self):
        url = build_customer_avatar_url(
            customer_id=7,
            business_id=3,
            ttl_seconds=900,
            base_url="https://crm.example.test",
        )

        self.assertTrue(url.startswith("https://crm.example.test/api/customers/7/avatar?"))
        query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
        self.assertEqual("3", query["business_id"])
        self.assertTrue(
            verify_customer_avatar_url(
                customer_id=7,
                business_id=3,
                expires=int(query["expires"]),
                signature=query["signature"],
            )
        )
        self.assertFalse(
            verify_customer_avatar_url(
                customer_id=8,
                business_id=3,
                expires=int(query["expires"]),
                signature=query["signature"],
            )
        )

    def test_build_avatar_url_normalizes_a_callback_path_from_legacy_env(self):
        url = build_customer_avatar_url(
            customer_id=7,
            business_id=3,
            base_url="https://crm.example.test/api/oauth/meta/callback",
        )
        self.assertTrue(url.startswith("https://crm.example.test/api/customers/7/avatar?"))

    def test_expired_signed_avatar_url_is_reissued_for_profile_responses(self):
        stale = (
            "https://crm.example.test/api/customers/7/avatar?"
            "business_id=3&expires=1&signature=expired"
        )

        reissue = getattr(customer_avatar, "refresh_customer_avatar_url", None)
        self.assertIsNotNone(reissue)
        refreshed = reissue(
            stale,
            customer_id=7,
            business_id=3,
            base_url="https://crm.example.test",
        )

        self.assertNotEqual(stale, refreshed)
        query = parse_qs(urlsplit(refreshed).query)
        self.assertGreater(int(query["expires"][0]), 1)
        self.assertTrue(
            verify_customer_avatar_url(
                customer_id=7,
                business_id=3,
                expires=int(query["expires"][0]),
                signature=query["signature"][0],
            )
        )


class CustomerAvatarApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        cls.previous_key = settings.CHANNEL_ENCRYPTION_KEY
        settings.CHANNEL_ENCRYPTION_KEY = "avatar-api-encryption-key"
        with Session(cls.engine) as db:
            business = Business(name="Avatar API Shop", slug="avatar-api-shop")
            db.add(business)
            db.flush()
            channel = Channel(
                business_id=business.id,
                channel_type="telegram",
                name="Telegram",
                external_account_id="bot-avatar-api",
                access_token_encrypted=encrypt_token(
                    "bot-token-secret",
                    settings.CHANNEL_ENCRYPTION_KEY,
                ),
            )
            db.add(channel)
            db.flush()
            customer = Customer(
                business_id=business.id,
                channel="telegram",
                external_user_id="12345",
                name="Telegram Buyer",
            )
            db.add(customer)
            db.flush()
            db.add(
                CustomerIdentity(
                    business_id=business.id,
                    customer_id=customer.id,
                    channel="telegram",
                    external_account_id=channel.external_account_id,
                    external_user_id=customer.external_user_id,
                )
            )
            db.commit()
            cls.business_id = business.id
            cls.customer_id = customer.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        settings.CHANNEL_ENCRYPTION_KEY = cls.previous_key

    def test_signed_avatar_route_streams_telegram_image_without_token(self):
        signed = build_customer_avatar_url(
            customer_id=self.customer_id,
            business_id=self.business_id,
            base_url="http://testserver",
        )
        parts = urlsplit(signed)
        query = parse_qs(parts.query)
        provider_response = Mock()
        provider_response.content = b"fake-jpeg"
        provider_response.headers = {"content-type": "image/jpeg"}
        provider_response.raise_for_status.return_value = None

        with patch(
            "app.api.customer_avatar.TelegramAdapter.fetch_profile_avatar_file_path",
            return_value="photos/avatar.jpg",
        ), patch(
            "app.api.customer_avatar.TelegramAdapter.build_file_url",
            return_value="https://api.telegram.org/file/botinternal/photos/avatar.jpg",
        ), patch("app.api.customer_avatar.httpx.get", return_value=provider_response) as get:
            response = self.client.get(f"{parts.path}?{parts.query}")

        self.assertEqual(200, response.status_code)
        self.assertEqual(b"fake-jpeg", response.content)
        self.assertEqual("image/jpeg", response.headers["content-type"])
        self.assertNotIn("bot-token-secret", get.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
