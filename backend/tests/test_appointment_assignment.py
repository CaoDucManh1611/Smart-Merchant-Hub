from datetime import datetime
from unittest.mock import MagicMock

import pytest
from app.services import appointment_assignment as assignment


@pytest.mark.parametrize("online,staff,conflicts,expected", [
    ([], [], [], None),
    (["9"], [(9,)], [None], 9),
    (["9"], [], [], None),
    (["9", "10"], [(9,), (10,)], [(1,), None], 10),
    (["9"], [(9,)], [(1,)], None),
])
def test_assignment_requires_online_eligible_staff_without_overlap(monkeypatch, online, staff, conflicts, expected):
    store = MagicMock()
    store.zrangebyscore.return_value = online
    monkeypatch.setattr(assignment, "presence_store", lambda: store)
    db, identities = MagicMock(), MagicMock()
    db.get_bind.return_value.dialect.name = "sqlite"
    db.query.return_value.filter.return_value.first.side_effect = conflicts
    identities.query.return_value.filter.return_value.all.return_value = staff
    assert assignment.choose_assignee(db, 7, datetime(2026, 11, 25, 5, 30),
                                     datetime(2026, 11, 25, 6, 30), user_db=identities) == expected
    if online:
        assert "staff-presence:7" in store.zrangebyscore.call_args.args[0]


def test_presence_failure_leaves_unassigned(monkeypatch):
    def unavailable():
        raise ConnectionError()
    monkeypatch.setattr(assignment, "presence_store", unavailable)
    assert assignment.choose_assignee(MagicMock(), 7, datetime.now(), datetime.now()) is None


def test_vietnamese_notes_convert_time_and_payment():
    fields = [{"key": "appointment_time", "label": "Thời gian mong muốn", "type": "datetime"},
              {"key": "payment_method", "label": "Hình thức thanh toán", "type": "text"}]
    notes = assignment.booking_notes(8, fields, {
        "appointment_time": "2026-11-25T05:30:00+00:00", "payment_method": "cod",
    }, "Asia/Ho_Chi_Minh")
    assert "Chờ nhân viên xác nhận" in notes
    assert "25/11/2026 12:30" in notes
    assert "Thanh toán khi nhận hàng (COD)" in notes
    assert "staff approval" not in notes
