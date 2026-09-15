"""Channel credentials and global routes must be committed as one saga."""

from pathlib import Path


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
