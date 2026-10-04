from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch
import pytest
from fastapi import HTTPException

from app.services.auto_reply_service import (
    _social_reply,
    _claim_auto_reply,
    _send_channel_reply,
    format_product_catalog_reply,
    process_rag_auto_reply,
    send_text_reply,
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("hello", "Hi!"),
        ("chào nha", "Chào bạn!"),
        ("tôi đâu hỏi bình giữ nhiệt gì đâu", "xin lỗi"),
    ],
)
def test_social_turn_does_not_inherit_old_product(message, expected):
    reply = _social_reply(message)
    assert reply is not None
    assert expected.casefold() in reply.casefold()
    assert "bình giữ nhiệt" not in reply.casefold()


def test_product_question_is_not_routed_as_social_turn():
    assert _social_reply("Bình giữ nhiệt inox 600 ml còn hàng không?") is None


def test_short_greeting_does_not_reuse_product_context():
    assert _social_reply("shop nha") is not None


def test_shopee_bridge_auth_error_does_not_force_human_takeover():
    db = Mock()
    conversation = Mock(bot_mode="auto")
    db.query.return_value.filter.return_value.first.return_value = conversation
    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
        patch("app.services.auto_reply_service.send_text_reply", side_effect=HTTPException(401, "bridge secret mismatch")), \
        patch("app.services.auto_reply_service._notify_rag_handoff_required") as handoff:
        with pytest.raises(HTTPException) as error:
            process_rag_auto_reply(db, 7, "shopee", "hello", 4)
    assert error.value.status_code == 401
    assert conversation.bot_mode == "auto"
    handoff.assert_not_called()
from app.services.quota_service import QuotaDecision, QuotaExceededError


def test_shopee_suppresses_same_auto_reply_within_short_cooldown():
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = Mock(status="sent")
    with patch("app.services.auto_reply_service._record_duplicate_reply_attempt") as record:
        claimed = _claim_auto_reply(
            db,
            conversation_id=24,
            channel="shopee",
            recipient_id="buyer-1",
            content="Bạn muốn mua sản phẩm nào?",
            business_id=3,
            auto_reply_key="inbound-2:reply-1",
        )

    assert claimed is False
    db.add.assert_not_called()
    db.commit.assert_not_called()
    record.assert_called_once_with(
        db,
        business_id=3,
        conversation_id=24,
        auto_reply_key="inbound-2:reply-1",
    )


def test_unknown_shopee_delivery_is_not_automatically_sent_again():
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = Mock(status="delivery_unknown")
    with patch("app.services.auto_reply_service._get_conversation_recipient", return_value=("shopee", "buyer-1")), \
         patch("app.services.auto_reply_service._claim_auto_reply", return_value=False), \
         patch("app.services.auto_reply_service._send_channel_reply") as send:
        with pytest.raises(HTTPException) as error:
            send_text_reply(db=db, conversation_id=24, channel="shopee", text="Dạ còn hàng ạ.",
                            business_id=3, auto_reply_key="turn:3:24:1:2")
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "delivery_unknown"
    send.assert_not_called()


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


def test_auto_reply_dispatches_facebook_and_instagram_through_mocked_meta_adapters():
    db = Mock()
    for channel, sender_name in (("facebook", "send_facebook_message"), ("instagram", "send_instagram_message")):
        with patch(f"app.services.auto_reply_service.{sender_name}", return_value={"message_id": f"{channel}:out-1"}) as send:
            response = _send_channel_reply(
                db=db, conversation_id=11, channel=channel, recipient_id="customer-1",
                text="Hello!", business_id=4,
            )
        assert response["message_id"] == f"{channel}:out-1"
        send.assert_called_once_with(recipient_id="customer-1", text="Hello!", db=db, business_id=4)


def test_auto_reply_dispatches_shopee_and_tiktok_through_existing_connectors():
    conversation = Mock(id=9, channel_id=3)
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = conversation

    for channel, sender_name in (
        ("shopee", "send_shopee_text"),
        ("tiktok", "send_tiktok_text"),
    ):
        with patch(
            f"app.api.conversations.{sender_name}",
            return_value=({"message_id": f"{channel}:42"}, channel),
        ) as send:
            response = _send_channel_reply(
                db=db,
                conversation_id=9,
                channel=channel,
                recipient_id="customer-1",
                text="Bạn muốn mua sản phẩm nào?",
                business_id=12,
            )

        assert response == {"message_id": f"{channel}:42"}
        send.assert_called_once_with(
            db=db,
            conversation={"id": 9, "channel_id": 3},
            recipient_id="customer-1",
            text_content="Bạn muốn mua sản phẩm nào?",
            business_id=12,
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


def test_english_product_discovery_uses_live_catalog_in_english_before_rag():
    db = Mock()
    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
        patch("app.services.auto_reply_service.customer_order_reply", return_value=None), \
        patch("app.services.product_pricing.combo_price_comparison_reply", return_value=None), \
        patch("app.services.auto_reply_service._deterministic_customer_reply", return_value=None), \
        patch("app.services.auto_reply_service.retrieve") as retrieve, \
        patch(
            "app.services.auto_reply_service.build_product_catalog_reply",
            return_value="Here are the shop's products:\n- Serum — ₫200,000 (8 available)",
        ) as catalog, \
        patch("app.services.auto_reply_service.send_text_reply") as send:
        result = process_rag_auto_reply(
            db=db,
            conversation_id=4,
            channel="telegram",
            query_text="I want to buy product",
            business_id=1,
        )

    assert result is True
    retrieve.assert_not_called()
    catalog.assert_called_once_with(db, 1, language="en")
    assert "Here are the shop's products" in send.call_args.kwargs["text"]


def test_rag_without_context_sends_safe_handoff_without_calling_llm():
    conversation = Mock(
        id=4,
        customer_id=8,
        assigned_user_id=None,
        bot_mode="auto",
        resolution_outcome=None,
    )
    db = Mock()
    db.query().filter().first.side_effect = [None, conversation]
    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
        patch("app.services.auto_reply_service.customer_order_reply", return_value=None), \
        patch("app.services.auto_reply_service.is_browsing_request", return_value=False), \
        patch("app.services.auto_reply_service.retrieve", return_value=[]), \
        patch("app.services.auto_reply_service.call_llm") as call_llm, \
        patch("app.services.auto_reply_service.send_text_reply", return_value={"message_id": "out-1"}) as send, \
        patch("app.services.auto_reply_service.create_notification") as create_notification, \
        patch("app.services.auto_reply_service._notify_rag_handoff_required") as handoff:
        result = process_rag_auto_reply(
            db=db,
            conversation_id=4,
            channel="telegram",
            query_text="Địa chỉ shop ở đâu?",
            business_id=1,
        )

    assert result is True
    assert conversation.bot_mode == "auto"
    assert conversation.resolution_outcome is None
    create_notification.assert_not_called()
    handoff.assert_called_once()
    call_llm.assert_not_called()
    assert "chưa có đủ thông tin" in send.call_args.kwargs["text"].lower()


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

    english_reply = format_product_catalog_reply([
        Product("Serum Vitamin C", 420000, 8, 2),
        Product("Kem chống nắng", 289000, 0),
    ], language="en")
    assert "Here are the shop's products:" in english_reply
    assert "₫420,000 (6 available)" in english_reply
    assert "₫289,000 (out of stock)" in english_reply


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
        patch("app.services.auto_reply_service.call_llm", return_value="answer [Nguồn 1]") as call_llm, \
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


def test_uncited_rag_auto_reply_hands_off_without_sending_generated_text():
    db = Mock()
    chunk = Mock(document_id=3, similarity=0.9, content="Hội viên được tích điểm theo đơn hàng.")
    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
        patch("app.services.auto_reply_service.customer_order_reply", return_value=None), \
        patch("app.services.auto_reply_service.is_browsing_request", return_value=False), \
        patch("app.services.auto_reply_service.retrieve", return_value=[chunk]), \
        patch("app.services.auto_reply_service.build_agent_memory", return_value={"history": []}), \
        patch("app.services.auto_reply_service.build_prompt", return_value=[{"role": "user", "content": "q"}]), \
        patch("app.services.auto_reply_service.record_quota_usage"), \
        patch("app.services.auto_reply_service.call_llm", return_value="Giá bịa 100.000 đồng."), \
        patch("app.services.auto_reply_service._notify_rag_handoff_required") as handoff, \
        patch("app.services.auto_reply_service.send_text_reply", return_value={"message_id": "safe-1"}) as send:
        result = process_rag_auto_reply(
            db=db, conversation_id=4, channel="telegram",
            query_text="Quy định hội viên ra sao?", business_id=1,
        )

    assert result is True
    assert "Giá bịa" not in send.call_args.kwargs["text"]
    assert "chưa có đủ thông tin" in send.call_args.kwargs["text"].lower()
    handoff.assert_called_once()
