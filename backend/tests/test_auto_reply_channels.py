from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch

from app.services.auto_reply_service import (
    _send_channel_reply,
    format_product_catalog_reply,
    process_rag_auto_reply,
    send_text_reply,
)
from app.services.quota_service import QuotaDecision, QuotaExceededError


def test_auto_reply_dispatches_telegram_through_tenant_channel():
    db = Mock()
    with patch(
        "app.services.auto_reply_service.send_telegram_message",
        return_value={"ok": True, "result": {"message_id": 42}},
    ) as send:
        response = _send_channel_reply(
            db=db,
            conversation_id=7,
            channel="telegram",
            recipient_id="12345",
            text="Serum Vitamin C giá 420.000 đồng.",
            business_id=1,
        )

    assert response["ok"] is True
    send.assert_called_once_with(
        db=db,
        business_id=1,
        conversation_id=7,
        recipient_id="12345",
        text="Serum Vitamin C giá 420.000 đồng.",
    )


def test_auto_reply_dispatches_zalo_through_tenant_channel():
    db = Mock()
    with patch(
        "app.services.auto_reply_service.send_zalo_message",
        return_value={"ok": True, "result": {"message_id": "z-out-1"}},
    ) as send:
        response = _send_channel_reply(
            db=db,
            conversation_id=8,
            channel="zalo",
            recipient_id="z-user-1",
            text="Serum Vitamin C giá 420.000 đồng.",
            business_id=1,
        )

    assert response["ok"] is True
    send.assert_called_once_with(
        db=db,
        business_id=1,
        conversation_id=8,
        recipient_id="z-user-1",
        text="Serum Vitamin C giá 420.000 đồng.",
    )


def test_static_reply_uses_conversation_channel_and_persists_message():
    db = Mock()
    with patch(
        "app.services.auto_reply_service._get_conversation_recipient",
        return_value=("telegram", "12345"),
    ), patch(
        "app.services.auto_reply_service._send_channel_reply",
        return_value={"message_id": "telegram:bot:99"},
    ) as send, patch(
        "app.services.auto_reply_service._save_auto_reply_outbound",
    ) as save:
        response = send_text_reply(
            db=db,
            conversation_id=7,
            channel="telegram",
            text="Chào bạn!",
            business_id=1,
        )

    assert response["message_id"] == "telegram:bot:99"
    send.assert_called_once_with(
        db=db,
        conversation_id=7,
        channel="telegram",
        recipient_id="12345",
        text="Chào bạn!",
        business_id=1,
    )
    save.assert_called_once_with(
        db=db,
        conversation_id=7,
        channel="telegram",
        recipient_id="12345",
        external_message_id="telegram:bot:99",
        content="Chào bạn!",
        meta_response={"message_id": "telegram:bot:99"},
        source_document_ids=[],
    )


def test_product_question_falls_back_to_tenant_catalog_when_rag_has_no_chunks():
    db = Mock()
    with patch(
        "app.services.auto_reply_service.get_auto_reply_enabled",
        return_value=True,
    ), patch(
        "app.services.auto_reply_service.retrieve",
        return_value=[],
    ), patch(
        "app.services.auto_reply_service.is_browsing_request",
        return_value=True,
    ), patch(
        "app.services.auto_reply_service.build_product_catalog_reply",
        return_value="Mình đang có các sản phẩm:\n- Serum Vitamin C — 420.000 đồng.",
    ), patch(
        "app.services.auto_reply_service.send_text_reply",
        return_value={"message_id": "zalo:shop:1"},
    ) as send:
        result = process_rag_auto_reply(
            db=db,
            conversation_id=4,
            channel="instagram",
            query_text="Bạn có sản phẩm gì?",
            business_id=1,
        )

    assert result is True
    send.assert_called_once_with(
        db=db,
        conversation_id=4,
        channel="instagram",
        text="Mình đang có các sản phẩm:\n- Serum Vitamin C — 420.000 đồng.",
        business_id=1,
    )


def test_order_status_reply_bypasses_rag_and_uses_customer_scoped_flow():
    db = Mock()
    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
        patch(
            "app.services.auto_reply_service.customer_order_reply",
            return_value="Đơn ORD-1 đang ở trạng thái Đã xác nhận.",
        ), \
        patch("app.services.auto_reply_service.retrieve") as retrieve, \
        patch("app.services.auto_reply_service.send_text_reply") as send:
        result = process_rag_auto_reply(
            db=db,
            conversation_id=4,
            channel="telegram",
            query_text="Kiểm tra trạng thái đơn ORD-1",
            business_id=1,
        )

    assert result is True
    retrieve.assert_not_called()
    send.assert_called_once_with(
        db=db,
        conversation_id=4,
        channel="telegram",
        text="Đơn ORD-1 đang ở trạng thái Đã xác nhận.",
        business_id=1,
    )


def test_product_discovery_bypasses_rag_even_when_knowledge_chunks_exist():
    db = Mock()
    chunk = Mock(document_id=9, similarity=0.95)
    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
        patch("app.services.auto_reply_service.is_browsing_request", return_value=True), \
        patch("app.services.auto_reply_service.retrieve", return_value=[chunk]) as retrieve, \
        patch(
            "app.services.auto_reply_service.build_product_catalog_reply",
            return_value="Mình đang có các sản phẩm:\n- Serum Vitamin C — 420.000 đồng.",
        ), \
        patch("app.services.auto_reply_service.send_text_reply") as send, \
        patch("app.services.auto_reply_service.call_llm") as call_llm:
        result = process_rag_auto_reply(
            db=db,
            conversation_id=4,
            channel="telegram",
            query_text="Bạn có sản phẩm gì?",
            business_id=1,
        )

    assert result is True
    retrieve.assert_not_called()
    call_llm.assert_not_called()
    send.assert_called_once_with(
        db=db,
        conversation_id=4,
        channel="telegram",
        text="Mình đang có các sản phẩm:\n- Serum Vitamin C — 420.000 đồng.",
        business_id=1,
    )


def test_product_catalog_reply_formats_price_and_stock():
    class Product:
        def __init__(self, name, price, stock_quantity, reserved_quantity=0):
            self.name = name
            self.price = price
            self.stock_quantity = stock_quantity
            self.reserved_quantity = reserved_quantity

    reply = format_product_catalog_reply([
        Product("Serum Vitamin C", 420000, 8, 2),
        Product("Kem chống nắng", 289000, 0),
    ])

    assert "Serum Vitamin C — 420.000 đồng (còn 6)" in reply
    assert "Kem chống nắng — 289.000 đồng (hết hàng)" in reply


def test_rag_auto_reply_checks_ai_quota_before_calling_llm():
    db = Mock()
    quota_error = QuotaExceededError(
        QuotaDecision(
            allowed=False,
            resource="ai_calls",
            used=Decimal("10"),
            limit=Decimal("10"),
            requested=Decimal("1"),
            period_start=datetime(2026, 9, 1),
        )
    )
    chunk = Mock(document_id=3, similarity=0.9)
    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.services.auto_reply_service.retrieve", return_value=[chunk]), \
        patch("app.services.auto_reply_service.build_agent_memory", return_value={"history": []}), \
        patch("app.services.auto_reply_service.build_prompt", return_value=[{"role": "user", "content": "q"}]), \
        patch("app.services.auto_reply_service.record_quota_usage", side_effect=quota_error), \
        patch("app.services.auto_reply_service.call_llm") as call_llm:
        result = process_rag_auto_reply(
            db=db,
            conversation_id=4,
            channel="telegram",
            query_text="giá serum",
            business_id=1,
        )

    assert result is False
    call_llm.assert_not_called()


def test_rag_auto_reply_reserves_ai_cost_before_calling_llm():
    db = Mock()
    chunk = Mock(document_id=3, similarity=0.9)
    quota_calls = []

    def reserve(_db, _business_id, resource, amount=1, **kwargs):
        quota_calls.append((resource, amount, kwargs.get("idempotency_key")))
        return None

    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
        patch("app.services.auto_reply_service.customer_order_reply", return_value=None), \
        patch("app.services.auto_reply_service.is_browsing_request", return_value=False), \
        patch("app.services.auto_reply_service.retrieve", return_value=[chunk]), \
        patch("app.services.auto_reply_service.build_agent_memory", return_value={"history": []}), \
        patch("app.services.auto_reply_service.build_prompt", return_value=[{"role": "user", "content": "q"}]), \
        patch("app.services.auto_reply_service.record_quota_usage", side_effect=reserve), \
        patch("app.services.auto_reply_service.call_llm", return_value="answer") as call_llm, \
        patch("app.services.auto_reply_service._get_conversation_recipient", return_value=("telegram", "customer-1")), \
        patch("app.services.auto_reply_service._send_channel_reply", return_value={"message_id": "out-1"}), \
        patch("app.services.auto_reply_service._save_auto_reply_outbound"):
        result = process_rag_auto_reply(
            db=db,
            conversation_id=4,
            channel="telegram",
            query_text="chính sách đổi trả",
            business_id=1,
        )

    assert result is True
    assert [item[0] for item in quota_calls] == ["ai_calls", "ai_cost"]
    assert quota_calls[1][1] > 0
    assert str(quota_calls[1][2]).startswith("rag-cost:")
    call_llm.assert_called_once()
