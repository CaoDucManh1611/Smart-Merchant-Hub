from datetime import datetime, timedelta
from types import SimpleNamespace

from scripts.export_rag_faq_candidates import pair_handoff_turn
from app.services.auto_reply_service import _inbound_message_id_from_handoff_key


def _message(message_id, direction, sender_type, content, at):
    return SimpleNamespace(
        id=message_id,
        direction=direction,
        sender_type=sender_type,
        content=content,
        received_at=at if direction == "inbound" else None,
        sent_at=at if direction == "outbound" else None,
    )


def test_handoff_export_pairs_exact_question_with_same_turn_staff_reply():
    start = datetime(2026, 11, 3, 10)
    rows = [
        _message(10, "inbound", "customer", "Hỏi giá sản phẩm A", start),
        _message(11, "outbound", "bot", "Mình nhờ nhân viên kiểm tra", start + timedelta(minutes=1)),
        _message(12, "outbound", "staff", "Giá hiện tại là 200.000 đồng", start + timedelta(minutes=4)),
        _message(13, "inbound", "customer", "Sản phẩm B còn hàng không?", start + timedelta(minutes=5)),
        _message(14, "outbound", "staff", "Sản phẩm B còn 3 chiếc", start + timedelta(minutes=6)),
    ]

    question, answer = pair_handoff_turn(
        rows, start + timedelta(minutes=2), question_message_id=10,
    )

    assert question.id == 10
    assert answer.id == 12


def test_legacy_handoff_uses_timestamp_and_does_not_borrow_later_turn():
    start = datetime(2026, 11, 3, 10)
    rows = [
        _message(20, "inbound", "customer", "Câu hỏi cũ", start),
        _message(21, "inbound", "customer", "Câu hỏi mới", start + timedelta(minutes=5)),
        _message(22, "outbound", "staff", "Câu trả lời mới", start + timedelta(minutes=6)),
    ]

    assert pair_handoff_turn(rows, start + timedelta(minutes=2)) is None
    question, answer = pair_handoff_turn(rows, start + timedelta(minutes=5, seconds=30))
    assert (question.id, answer.id) == (21, 22)


def test_handoff_key_retains_exact_inbound_message_identity():
    assert _inbound_message_id_from_handoff_key(
        "rag-handoff:inbound:7:22:431:default",
    ) == 431
    assert _inbound_message_id_from_handoff_key("rag-handoff:legacy-hash") is None
