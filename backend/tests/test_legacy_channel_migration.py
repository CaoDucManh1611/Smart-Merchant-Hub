import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.business import Business
from app.models.channel import Channel
from app.models.channel_migration import ChannelMigrationAudit
from app.models.setting import AppSetting
from app.core.config import settings
from app.services.legacy_channel_migration import migrate_legacy_channels


class LegacyChannelMigrationTests(unittest.TestCase):
    def test_unmapped_legacy_channel_is_skipped_and_reported(self):
        engine = create_engine("sqlite://")
        Business.metadata.create_all(engine)
        with Session(engine) as db:
            settings.CHANNEL_ENCRYPTION_KEY = "test-key"
            db.add_all([
                AppSetting(key="meta.facebook_page_id", value="page-1"),
                AppSetting(key="meta.facebook_page_access_token", value="token-1"),
            ])
            db.commit()
            report = migrate_legacy_channels(db, mapping={}, encryption_key="test-key")
            self.assertEqual("skipped", report["items"][0]["status"])
            self.assertEqual([], db.query(Channel).all())

    def test_migration_is_idempotent_for_explicit_mapping(self):
        engine = create_engine("sqlite://")
        Business.metadata.create_all(engine)
        with Session(engine) as db:
            settings.CHANNEL_ENCRYPTION_KEY = "test-key"
            business = Business(name="Shop", slug="shop")
            db.add(business)
            db.add_all([
                AppSetting(key="meta.facebook_page_id", value="page-1"),
                AppSetting(key="meta.facebook_page_name", value="Page"),
                AppSetting(key="meta.facebook_page_access_token", value="token-1"),
            ])
            db.commit()
            mapping = {"facebook:page-1": business.id}
            # Do not let a developer machine's Instagram .env values add
            # unrelated candidates to this focused Facebook test.
            with patch.object(settings, "FACEBOOK_PAGE_ID", ""), \
                 patch.object(settings, "FACEBOOK_PAGE_ACCESS_TOKEN", ""), \
                 patch.object(settings, "INSTAGRAM_ACCOUNT_ID", ""), \
                 patch.object(settings, "INSTAGRAM_ACCESS_TOKEN", ""):
                migrate_legacy_channels(db, mapping=mapping, encryption_key="test-key")
                migrate_legacy_channels(db, mapping=mapping, encryption_key="test-key")
            self.assertEqual(1, db.query(Channel).count())
            self.assertEqual(2, db.query(ChannelMigrationAudit).count())


if __name__ == "__main__":
    unittest.main()
