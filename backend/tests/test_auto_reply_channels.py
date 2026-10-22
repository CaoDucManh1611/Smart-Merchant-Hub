from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch
import pytest
from fastapi import HTTPException

from app.services.auto_reply_service import (
    _social_reply,
    _claim_auto_reply,
    _deterministic_customer_reply,
    _extract_vietqr_photo,
    _send_channel_reply,
    format_product_catalog_reply,
    process_rag_auto_reply,
    send_text_reply,
)


@pytest.mark.parametrize("label", ["Mã QR", "• Mã QR", "🧾 Mã QR"])
def test_vietqr_invoice_marker_is_sent_as_image_even_with_display_prefix(label):
    url = "https://img.vietqr.io/image/970403-0327256842-compact2.png?amount=4980000&addInfo=CHAT26"
    text = f"🧾 Hóa đơn tạm tính CHAT-26\n{label}: {url}\nShop xác nhận sau khi nhận tiền."

    assert _extract_vietqr_photo(text) == (
        url,
        "🧾 Hóa đơn tạm tính CHAT-26\nShop xác nhận sau khi nhận tiền.",
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


@pytest.mark.parametrize(
    ("query", "expected_route", "source_type"),
    [
        ("Sản phẩm nào bán chạy nhất tháng này?", "sales_rank", "crm_sales_rank"),
        ("Doanh thu tháng này bao nhiêu?", "sales_revenue", "crm_sales_summary"),
    ],
)
def test_sales_questions_on_channel_bot_use_crm_not_rag(query, expected_route, source_type):
    from app.schemas.rag import ChatResponse

    metadata = {}
    response = ChatResponse(
        answer="Số liệu lấy trực tiếp từ CRM.", sources=[], chunks_found=0,
        data_sources=[{"type": source_type, "period": "2026-10"}],
    )
    with patch("app.services.crm_knowledge._monthly_bestseller_reply", return_value=response), \
         patch("app.services.crm_knowledge._monthly_revenue_reply", return_value=response):
        reply, route = _deterministic_customer_reply(
            Mock(), business_id=7, conversation_id=3, query_text=query, reply_metadata=metadata,
        )

    assert reply == response.answer
    assert route == expected_route
    assert metadata["crm_data_sources"][0]["type"] == source_type


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


def test_delivery_unknown_pauses_bot_and_notifies_staff_without_retry():
    from app.services.auto_reply_service import _notify_rag_handoff_required

    conversation = Mock(
        id=7, customer_id=8, assigned_user_id=None,
        bot_mode="auto", resolution_outcome=None,
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = conversation
    unknown = HTTPException(409, detail={"code": "delivery_unknown"})
    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
         patch("app.services.auto_reply_service.is_business_open", return_value=True), \
         patch("app.services.auto_reply_service._latest_inbound_image_url", return_value=None), \
         patch("app.services.auto_reply_service.send_text_reply", side_effect=unknown) as send, \
         patch("app.services.auto_reply_service.create_notification") as notify, \
         patch("app.services.auto_reply_service._notify_rag_handoff_required",
               wraps=_notify_rag_handoff_required) as handoff:
        result = process_rag_auto_reply(db, 7, "shopee", "hello", 4)

    assert result is True
    assert send.call_count == 1
    handoff.assert_called_once()
    assert handoff.call_args.kwargs["reason"] == "delivery_unknown"
    assert conversation.bot_mode == "human"
    assert conversation.resolution_outcome == "needs_human"
    notify.assert_called_once()
from app.services.quota_service import QuotaDecision, QuotaExceededError


@pytest.mark.parametrize("channel", ["facebook", "instagram", "telegram", "zalo", "tiktok", "shopee"])
def test_product_attributes_use_same_current_crm_context_on_all_channels(channel):
    from contextlib import ExitStack
    from types import SimpleNamespace
    from app.rag.retriever import RetrievedChunk
    product = SimpleNamespace(id=1, sku="DM-APP-001", name="Áo hồng", description="Cotton",
                              price=100000, stock_quantity=20, reserved_quantity=2)
    evidence = RetrievedChunk(12, 7, "DM-APP-001 có thành phần cotton. Giá cũ 999000 VND.", .9, {})
    with ExitStack() as stack:
        def mock(name, **kwargs):
            return stack.enter_context(patch("app.services.auto_reply_service." + name, **kwargs))
        mock("get_auto_reply_enabled", return_value=True)
        mock("is_business_open", return_value=True)
        mock("_latest_inbound_image_url", return_value=None)
        mock("customer_order_reply", return_value=None)
        mock("_find_exact_product", return_value=(product, "DM-APP-001"))
        mock("retrieve", return_value=[evidence])
        mock("build_agent_memory", return_value={
            "history": [],
            "facts": [{"key": "preferred_color", "value": "hồng", "verified": False}],
        })
        mock("record_explicit_chat_recommendation_decline", return_value=None)
        mock("select_chatbot_reply_choice", return_value=None)
        mock("record_quota_usage")
        mock("estimate_ai_cost", return_value=Decimal("0"))
        stack.enter_context(patch("app.services.product_pricing.combo_price_comparison_reply", return_value=None))
        model = mock("call_llm", return_value="DM-APP-001: cotton [Nguồn 2]; giá 100000 VND [Nguồn 1].")
        mock("_get_conversation_recipient", return_value=(channel, "fixture-customer"))
        send = mock("_send_channel_reply", return_value={"message_id": "fixture-out-1"})
        save = mock("_save_auto_reply_outbound")
        assert process_rag_auto_reply(Mock(), 4, channel, "DM-APP-001 thành phần gì?", 1)
        assert "CURRENT_CRM_PRODUCT" in str(model.call_args.args[0])
        assert "preferred_color" in str(model.call_args.args[0])
        assert send.call_args.kwargs["channel"] == channel
        assert "100000 VND" in send.call_args.kwargs["text"]
        assert "999000" not in send.call_args.kwargs["text"]
        assert save.call_args.kwargs["source_document_ids"] == [7]


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


def test_telegram_order_qr_is_sent_as_photo_with_instructions_as_caption():
    db = Mock()
    text = (
        "🏦 Thông tin chuyển khoản đơn CHAT-17\n"
        "Ngân hàng: Sacombank\nChủ tài khoản: Ngo Long Thien\n"
        "Số tiền: 249.000 đồng\nNội dung chuyển khoản: CHAT17\n"
        "Mã QR: https://img.vietqr.io/image/970403-0327256842-compact2.png?amount=249000&addInfo=CHAT17\n"
        "Shop sẽ cập nhật thanh toán sau khi xác nhận tiền đã vào tài khoản."
    )
    with patch(
        "app.services.auto_reply_service.send_telegram_media",
        return_value={"ok": True, "result": {"message_id": 43}},
    ) as send_photo, patch(
        "app.services.auto_reply_service.send_telegram_message",
    ) as send_text:
        response = _send_channel_reply(
            db=db,
            conversation_id=7,
            channel="telegram",
            recipient_id="12345",
            text=text,
            business_id=1,
        )

    assert response["ok"] is True
    send_photo.assert_called_once_with(
        db=db,
        business_id=1,
        conversation_id=7,
        recipient_id="12345",
        media_type="image",
        media_url="https://img.vietqr.io/image/970403-0327256842-compact2.png?amount=249000&addInfo=CHAT17",
        caption=(
            "🏦 Thông tin chuyển khoản đơn CHAT-17\n"
            "Ngân hàng: Sacombank\nChủ tài khoản: Ngo Long Thien\n"
            "Số tiền: 249.000 đồng\nNội dung chuyển khoản: CHAT17\n"
            "Shop sẽ cập nhật thanh toán sau khi xác nhận tiền đã vào tài khoản."
        ),
    )
    send_text.assert_not_called()


def test_facebook_and_instagram_order_qr_are_sent_as_images_without_the_url_text():
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = Mock(id=11, channel_id=5)
    text = (
        "Thông tin chuyển khoản CHAT-18\nNgân hàng: Sacombank\nSố tiền: 1.245.000 đồng\n"
        "Mã QR: https://img.vietqr.io/image/970403-0327256842-compact2.png?amount=1245000&addInfo=CHAT18\n"
        "Shop xác nhận sau khi nhận được tiền."
    )
    caption = "Thông tin chuyển khoản CHAT-18\nNgân hàng: Sacombank\nSố tiền: 1.245.000 đồng\nShop xác nhận sau khi nhận được tiền."

    for channel in ("facebook", "instagram"):
        with patch(
            "app.api.conversations.send_meta_image",
            return_value=({"status": "sent", "message_id": f"{channel}:image-1"}, Mock()),
        ) as send_image, patch("app.api.conversations.send_meta_text") as send_text:
            response = _send_channel_reply(
                db=db,
                conversation_id=11,
                channel=channel,
                recipient_id="customer-1",
                text=text,
                business_id=4,
            )

        assert response["media_type"] == "image"
        assert response["media_url"].startswith("https://img.vietqr.io/image/")
        assert response["caption"] == caption
        send_image.assert_called_once_with(
            db=db,
            conversation={"id": 11, "channel_id": 5, "channel": channel},
            recipient_id="customer-1",
            image_url="https://img.vietqr.io/image/970403-0327256842-compact2.png?amount=1245000&addInfo=CHAT18",
            caption=caption,
            business_id=4,
        )
        send_text.assert_not_called()


def test_auto_reply_persists_qr_caption_and_image_instead_of_url():
    db = Mock()
    text = (
        "Thông tin chuyển khoản CHAT-18\nSố tiền: 1.245.000 đồng\n"
        "Mã QR: https://img.vietqr.io/image/970403-account.png?amount=1245000\n"
        "Shop sẽ xác nhận."
    )
    caption = "Thông tin chuyển khoản CHAT-18\nSố tiền: 1.245.000 đồng\nShop sẽ xác nhận."
    with patch(
        "app.services.auto_reply_service._get_conversation_recipient",
        return_value=("instagram", "buyer-1"),
    ), patch(
        "app.services.auto_reply_service._send_channel_reply",
        return_value={
            "message_id": "meta-ui:thread-1:123",
            "media_type": "image",
            "media_url": "https://img.vietqr.io/image/970403-account.png?amount=1245000",
            "caption": caption,
        },
    ), patch("app.services.auto_reply_service._save_auto_reply_outbound") as save:
        send_text_reply(
            db=db,
            conversation_id=7,
            channel="instagram",
            text=text,
            business_id=1,
        )

    saved = save.call_args.kwargs
    assert saved["content"] == caption
    assert saved["meta_response"]["media_type"] == "image"
    assert saved["meta_response"]["media_url"].startswith("https://img.vietqr.io/image/")


def test_telegram_untrusted_qr_url_stays_as_plain_text():
    db = Mock()
    text = "Mã QR: https://img.vietqr.io.attacker.test/image/qr.png"
    with patch(
        "app.services.auto_reply_service.send_telegram_message",
        return_value={"ok": True},
    ) as send_text, patch(
        "app.services.auto_reply_service.send_telegram_media",
    ) as send_photo:
        _send_channel_reply(
            db=db,
            conversation_id=7,
            channel="telegram",
            recipient_id="12345",
            text=text,
            business_id=1,
        )

    send_text.assert_called_once()
    send_photo.assert_not_called()


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


def test_auto_reply_dispatches_facebook_and_instagram_through_meta_send_helper():
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = Mock(id=11, channel_id=5)
    for channel in ("facebook", "instagram"):
        with patch(
            "app.api.conversations.send_meta_text",
            return_value=({"message_id": f"{channel}:out-1"}, Mock()),
        ) as send:
            response = _send_channel_reply(
                db=db, conversation_id=11, channel=channel, recipient_id="customer-1",
                text="Hello!", business_id=4,
            )
        assert response["message_id"] == f"{channel}:out-1"
        send.assert_called_once_with(
            db=db,
            conversation={"id": 11, "channel_id": 5, "channel": channel},
            recipient_id="customer-1",
            text_content="Hello!",
            business_id=4,
        )


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
        patch("app.services.auto_reply_service.rag_personalization_weights", return_value=None), \
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


def test_instagram_image_is_passed_to_vision_model_and_gets_a_reply():
    db = Mock()
    conversation = Mock(bot_mode="auto", customer_id=8, resolution_outcome=None)
    db.query.return_value.filter.return_value.first.side_effect = [None, conversation]
    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
        patch("app.services.auto_reply_service._latest_inbound_image_url", return_value="https://scontent.cdninstagram.com/test.jpg"), \
        patch("app.services.auto_reply_service._download_meta_image", return_value=(b"image-bytes", "image/jpeg")), \
        patch("app.services.auto_reply_service.customer_order_reply", return_value=None), \
        patch("app.services.product_pricing.combo_price_comparison_reply", return_value=None), \
        patch("app.services.auto_reply_service.record_explicit_chat_recommendation_decline"), \
        patch("app.services.auto_reply_service._deterministic_customer_reply", return_value=None), \
        patch("app.services.auto_reply_service.is_browsing_request", return_value=False), \
        patch("app.services.auto_reply_service.rag_personalization_weights", return_value=None), \
        patch("app.services.auto_reply_service.retrieve", return_value=[]), \
        patch("app.services.auto_reply_service.select_chatbot_reply_choice", return_value=None), \
        patch("app.services.auto_reply_service.build_agent_memory", return_value={"history": []}), \
        patch("app.services.auto_reply_service.build_prompt", return_value=[{"role": "user", "content": "xem ảnh"}]), \
        patch("app.services.auto_reply_service.record_quota_usage"), \
        patch("app.services.auto_reply_service.estimate_ai_cost", return_value=Decimal("0")), \
        patch("app.services.auto_reply_service.call_llm") as text_model, \
        patch("app.services.auto_reply_service.call_llm_with_image", return_value="Mình thấy một chiếc áo màu hồng.") as vision_model, \
        patch("app.services.auto_reply_service._get_conversation_recipient", return_value=("instagram", "ig-customer")), \
        patch("app.services.auto_reply_service._send_channel_reply", return_value={"message_id": "ig-reply-1"}), \
        patch("app.services.auto_reply_service._save_auto_reply_outbound"):
        result = process_rag_auto_reply(
            db=db,
            conversation_id=4,
            channel="instagram",
            query_text="Màu gì trong ảnh?",
            business_id=1,
        )

    assert result is True
    vision_model.assert_called_once_with(
        [{"role": "user", "content": "xem ảnh"}], b"image-bytes", "image/jpeg"
    )
    text_model.assert_not_called()


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


def test_empty_rag_answer_sends_one_safe_handoff_reply():
    db = Mock()
    chunk = Mock(document_id=3, similarity=0.9, content="Chính sách đổi trả cần nhân viên xác nhận.")
    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
        patch("app.services.auto_reply_service.customer_order_reply", return_value=None), \
        patch("app.services.auto_reply_service.is_browsing_request", return_value=False), \
        patch("app.services.auto_reply_service.retrieve", return_value=[chunk]), \
        patch("app.services.auto_reply_service.build_agent_memory", return_value={"history": []}), \
        patch("app.services.auto_reply_service.build_prompt", return_value=[{"role": "user", "content": "q"}]), \
        patch("app.services.auto_reply_service.record_quota_usage"), \
        patch("app.services.auto_reply_service.call_llm", return_value="") as call_llm, \
        patch("app.services.auto_reply_service._notify_rag_handoff_required") as handoff, \
        patch("app.services.auto_reply_service.send_text_reply", return_value={"message_id": "safe-1"}) as send:
        result = process_rag_auto_reply(
            db=db, conversation_id=4, channel="telegram",
            query_text="Chính sách đổi trả ra sao?", business_id=1,
        )

    assert result is True
    call_llm.assert_called_once()
    send.assert_called_once()
    handoff.assert_called_once()
    assert "đang gặp sự cố" in send.call_args.kwargs["text"].lower()
