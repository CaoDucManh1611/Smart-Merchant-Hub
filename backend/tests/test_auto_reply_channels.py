from unittest.mock import Mock, patch

from app.services.auto_reply_service import (
    _send_channel_reply,
    format_product_catalog_reply,
    process_rag_auto_reply,
    send_text_reply,
)


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
