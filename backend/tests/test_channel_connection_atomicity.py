"""Channel credentials and global routes must be committed as one saga."""

from pathlib import Path
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.services import channel_service


ROOT = Path(__file__).resolve().parents[1]


def test_channel_upsert_can_join_an_outer_transaction():
    source = (ROOT / "app" / "services" / "channel_service.py").read_text(encoding="utf-8")
    assert "commit: bool = True" in source
    assert "if commit:" in source


def test_provider_connections_use_platform_quota_and_commit_after_route():
    source = (ROOT / "app" / "api" / "onboarding.py").read_text(encoding="utf-8")
    assert "reserve_quota(platform_db" in source
    assert "commit=False" in source
    # The compatibility/manual connection endpoint must not create an
    # orphaned tenant channel: every provider account needs a platform route
    # before the platform transaction is committed.
    manual = source.split("def connect_channel(", 1)[1].split("@router.get", 1)[0]
    assert "register_webhook_route(" in manual
    assert "webhook_secret =" in manual
    oauth = (ROOT / "app" / "api" / "meta_oauth.py").read_text(encoding="utf-8")
    assert "commit=False" in oauth


def test_reconnecting_a_channel_that_still_holds_a_slot_does_not_reserve_twice():
    engine = create_engine("sqlite://")
    Channel.__table__.create(engine)
    try:
        with Session(engine) as db:
            channel = Channel(
                business_id=7,
                channel_type="telegram",
                name="Old bot",
                external_account_id="telegram-7",
                status="reconnect_required",
            )
            db.add(channel)
            db.commit()

            reserve_slot = Mock()
            with patch.object(channel_service, "encrypt_token", return_value="encrypted"):
                result = channel_service.upsert_channel_connection(
                    db,
                    business_id=7,
                    channel_type="telegram",
                    external_account_id="telegram-7",
                    name="New bot",
                    access_token="new-token",
                    reserve_channel_slot=reserve_slot,
                )

            assert result.status == "active"
            reserve_slot.assert_not_called()
    finally:
        engine.dispose()
