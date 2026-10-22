from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.notifications import delete_all_notifications, mark_all_notifications_read
from app.models.notification import Notification
from app.tenancy.context import TenantContext


def test_mark_all_notifications_read_is_limited_to_current_shop_and_staff():
    engine = create_engine("sqlite://")
    Notification.__table__.create(engine)
    with Session(engine) as db:
        db.add_all([
            Notification(business_id=3, user_id=8, kind="new_message", title="Mine", is_read=False),
            Notification(business_id=3, user_id=None, kind="sla", title="Shared", is_read=False),
            Notification(business_id=3, user_id=9, kind="new_message", title="Other staff", is_read=False),
            Notification(business_id=4, user_id=8, kind="sla", title="Other shop", is_read=False),
            Notification(business_id=3, user_id=8, kind="sla", title="Already read", is_read=True),
        ])
        db.commit()

        result = mark_all_notifications_read(
            db=db,
            tenant=TenantContext(business_id=3, source="test"),
            user=SimpleNamespace(id=8),
        )

        assert result == {"updated_count": 2}
        states = {
            row.title: row.is_read
            for row in db.scalars(select(Notification)).all()
        }
        assert states == {
            "Mine": True,
            "Shared": True,
            "Other staff": False,
            "Other shop": False,
            "Already read": True,
        }


def test_delete_all_notifications_is_limited_to_current_shop_and_staff():
    engine = create_engine("sqlite://")
    Notification.__table__.create(engine)
    with Session(engine) as db:
        db.add_all([
            Notification(business_id=3, user_id=8, kind="new_message", title="Mine", is_read=False),
            Notification(business_id=3, user_id=None, kind="sla", title="Shared", is_read=True),
            Notification(business_id=3, user_id=9, kind="new_message", title="Other staff", is_read=False),
            Notification(business_id=4, user_id=8, kind="sla", title="Other shop", is_read=False),
        ])
        db.commit()

        result = delete_all_notifications(
            db=db,
            tenant=TenantContext(business_id=3, source="test"),
            user=SimpleNamespace(id=8),
        )

        assert result == {"deleted_count": 2}
        assert {row.title for row in db.scalars(select(Notification)).all()} == {"Other staff", "Other shop"}
