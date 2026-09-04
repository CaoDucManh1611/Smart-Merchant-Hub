import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Business, Channel
from app.tenancy.webhook import resolve_channel_business


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


if __name__ == "__main__":
    unittest.main()
