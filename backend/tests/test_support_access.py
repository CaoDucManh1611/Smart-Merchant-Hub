from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database.bases import PlatformBase
from app.models.platform_control import PlatformAudit, PlatformBusiness, PlatformUser
from app.services.support_access import (
    create_support_grant,
    issue_support_token,
    revoke_support_grant,
    validate_support_access,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    PlatformBase.metadata.create_all(engine)
    with Session(engine) as session:
        shop = PlatformBusiness(id=7, name="Shop 7", slug="shop-7")
        owner = PlatformUser(id=10, business_id=7, email="owner@example.test", full_name="Owner", role="owner")
        support = PlatformUser(id=20, business_id=None, email="support@example.test", full_name="Support", role="support")
        session.add_all([shop, owner, support])
        session.commit()
        yield session


def _expiry(minutes=20):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def test_support_grant_is_scoped_and_revocation_is_immediate(db):
    grant = create_support_grant(
        db,
        business_id=7,
        granted_by_user_id=10,
        support_user_id=20,
        reason="Kiểm tra lỗi webhook",
        scopes=["channels:diagnose", "jobs:retry"],
        expires_at=_expiry(),
    )
    db.commit()
    token, expires_at = issue_support_token(db, grant_id=grant.id, support_user_id=20)
    assert expires_at > datetime.now(timezone.utc).replace(tzinfo=None)
    assert "Kiểm tra" not in token

    session = validate_support_access(
        db,
        token=token,
        business_id=7,
        scope="channels:diagnose",
    )
    assert session.grant_id == grant.id
    assert session.scopes == ("channels:diagnose", "jobs:retry")

    with pytest.raises(PermissionError, match="phạm vi"):
        validate_support_access(db, token=token, business_id=7, scope="customer:read")
    with pytest.raises(PermissionError, match="shop này"):
        validate_support_access(db, token=token, business_id=8, scope="jobs:retry")

    revoke_support_grant(db, grant_id=grant.id, actor_user_id=10)
    db.commit()
    with pytest.raises(PermissionError, match="hết hạn|thu hồi"):
        validate_support_access(db, token=token, business_id=7, scope="jobs:retry")

    actions = [row.action for row in db.scalars(select(PlatformAudit)).all()]
    assert "support_grant_created" in actions
    assert "support_access_allowed" in actions
    assert "support_access_denied" in actions
    assert "support_grant_revoked" in actions


def test_only_owner_can_grant_and_content_scopes_are_rejected(db):
    with pytest.raises(ValueError, match="vận hành"):
        create_support_grant(
            db,
            business_id=7,
            granted_by_user_id=10,
            support_user_id=20,
            reason="Đọc tin nhắn khách",
            scopes=["conversation:read"],
            expires_at=_expiry(),
        )
    with pytest.raises(PermissionError, match="chủ shop"):
        create_support_grant(
            db,
            business_id=7,
            granted_by_user_id=20,
            support_user_id=20,
            reason="Chẩn đoán provider",
            scopes=["channels:diagnose"],
            expires_at=_expiry(),
        )


def test_grant_cannot_exceed_one_hour_or_be_expired(db):
    for minutes, message in ((61, "60 phút"), (-1, "tương lai")):
        with pytest.raises(ValueError, match=message):
            create_support_grant(
                db,
                business_id=7,
                granted_by_user_id=10,
                support_user_id=20,
                reason="Hỗ trợ vận hành",
                scopes=["jobs:retry"],
                expires_at=_expiry(minutes),
            )
