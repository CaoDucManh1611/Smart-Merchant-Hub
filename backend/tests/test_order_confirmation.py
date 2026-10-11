from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import order_confirmation as service


def order():
    return SimpleNamespace(id=7, order_number="ORD-7", conversation_id=12,
                           customer_id=3, total_amount=Decimal("2000"), metadata_={},
                           items=[SimpleNamespace(product=SimpleNamespace(name="Sản phẩm"),
                                                  quantity=2, unit_price=Decimal("1000"))])


def test_confirmation_uses_linked_conversation_and_stable_key(monkeypatch):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id=12, channel="shopee")
    send = MagicMock()
    monkeypatch.setattr(service, "send_text_reply", send)
    record = order()
    service.notify_order_confirmation(db, order=record, business_id=5)
    assert send.call_args.kwargs["conversation_id"] == 12
    assert send.call_args.kwargs["auto_reply_key"] == "order-confirmed:5:7"
    assert "2,000" in send.call_args.kwargs["text"]
    assert record.metadata_["confirmation_notification_status"] == "sent"


def test_missing_link_never_guesses_another_conversation(monkeypatch):
    db = MagicMock()
    record = order()
    record.conversation_id = None
    send = MagicMock()
    monkeypatch.setattr(service, "send_text_reply", send)
    service.notify_order_confirmation(db, order=record, business_id=5)
    send.assert_not_called()
    assert record.metadata_["confirmation_notification_status"] == "no_conversation"


def test_provider_failure_is_recorded_without_claiming_success(monkeypatch):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id=12, channel="shopee")
    monkeypatch.setattr(service, "send_text_reply", MagicMock(side_effect=RuntimeError("provider unavailable")))
    record = order()
    service.notify_order_confirmation(db, order=record, business_id=5)
    assert record.metadata_["confirmation_notification_status"] == "failed"
    db.rollback.assert_called_once()
