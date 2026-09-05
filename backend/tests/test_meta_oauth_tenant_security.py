"""Regression tests for tenant-safe Meta OAuth connection state."""

import asyncio
import unittest
from contextlib import nullcontext
from unittest.mock import Mock
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import meta_oauth
from app.models.business import Business
from app.models.channel import Channel
from app.tenancy.context import TenantContext


class MetaOAuthTenantSecurityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        with Session(self.engine) as db:
            first = Business(name="Meta One", slug="meta-one")
            second = Business(name="Meta Two", slug="meta-two")
            db.add_all([first, second])
            db.flush()
            db.add_all([
                Channel(
                    business_id=first.id,
                    channel_type="facebook",
                    name="First Page",
                    external_account_id="page-first",
                    access_token_encrypted="encrypted-first",
                    status="active",
                    config={"subscription_status": "subscribed_messages"},
                ),
                Channel(
                    business_id=first.id,
                    channel_type="instagram",
                    name="first.ig",
                    external_account_id="ig-first",
                    access_token_encrypted="encrypted-first-ig",
                    status="active",
                ),
                Channel(
                    business_id=second.id,
                    channel_type="facebook",
                    name="Second Page",
                    external_account_id="page-second",
                    access_token_encrypted="encrypted-second",
                    status="active",
                ),
            ])
            db.commit()
            self.first_business_id = first.id
            self.second_business_id = second.id

    def tearDown(self):
        self.engine.dispose()

    def test_status_reads_only_the_current_tenants_encrypted_channels(self):
        with patch.object(meta_oauth, "SessionLocal", self.session_factory):
            status = asyncio.run(
                meta_oauth.meta_oauth_status(TenantContext(self.first_business_id, "test"))
            )

        self.assertTrue(status["connected"])
        self.assertEqual("page-first", status["facebook_page_id"])
        self.assertEqual("ig-first", status["instagram_account_id"])
        self.assertEqual("subscribed_messages", status["subscription_status"])

    def test_start_can_return_the_provider_url_after_tenant_authentication(self):
        db = Mock()
        with (
            patch.object(meta_oauth, "SessionLocal", return_value=nullcontext(db)),
            patch.object(meta_oauth, "_require_oauth_settings", return_value=("app-id", "secret", "https://api.example/callback")),
            patch.object(meta_oauth, "issue_oauth_state", return_value="tenant-signed-state"),
            patch.object(meta_oauth, "register_oauth_state") as register_state,
        ):
            result = asyncio.run(
                meta_oauth.start_meta_oauth(
                    TenantContext(self.first_business_id, "test"),
                    return_url=True,
                )
            )

        self.assertIn("authorization_url", result)
        self.assertIn("state=tenant-signed-state", result["authorization_url"])
        register_state.assert_called_once_with(db, "tenant-signed-state", "secret")

    def test_start_route_disables_response_model_for_redirect_or_json_response(self):
        route = next(
            route for route in meta_oauth.router.routes
            if route.path == "/meta/start"
        )
        self.assertIsNone(route.response_model)

    def test_disconnect_revokes_only_the_current_tenants_credentials(self):
        with patch.object(meta_oauth, "SessionLocal", self.session_factory):
            response = asyncio.run(
                meta_oauth.disconnect_meta(TenantContext(self.first_business_id, "test"))
            )
        self.assertEqual({"connected": False}, response)

        with Session(self.engine) as db:
            first_channels = db.query(Channel).filter(
                Channel.business_id == self.first_business_id
            ).all()
            second_channel = db.query(Channel).filter(
                Channel.business_id == self.second_business_id,
                Channel.channel_type == "facebook",
            ).one()
        self.assertTrue(all(channel.status == "inactive" for channel in first_channels))
        self.assertTrue(all(channel.access_token_encrypted is None for channel in first_channels))
        self.assertEqual("active", second_channel.status)
        self.assertEqual("encrypted-second", second_channel.access_token_encrypted)


if __name__ == "__main__":
    unittest.main()
