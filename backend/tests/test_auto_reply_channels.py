from datetime import datetime
from decimal import Decimal
import json
from unittest.mock import Mock, patch
import pytest
from fastapi import HTTPException

from app.services.auto_reply_service import (
    _social_reply,
    _claim_auto_reply,
    _catalog_image_matching_allowed,
    _combo_price_comparison_reply_if_allowed,
    _deterministic_customer_reply,
    _extract_vietqr_photo,
    _is_product_catalog_listing_request,
    _record_rag_handoff,
    _send_channel_reply,
    format_product_catalog_reply,
    process_rag_auto_reply,
    send_text_reply,
)


def _catalog_enabled_workspace_config():
    return {
        "business_model": "RETAIL",
        "enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS", "RECOMMENDATION_TOOLS", "RENTAL_TOOLS"],
        "available_dependencies": [
            "tenant_crm", "conversation_service", "product_catalog", "pricing",
            "recommendation_service", "personalization_consent", "rental_offerings",
            "rental_availability", "rental_workflow",
        ],
    }


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


@pytest.mark.parametrize("query", [
    "Giá của XM-NSD-WA110 bao nhiêu?",
    "Gợi ý sản phẩm phù hợp cho tôi",
])
def test_direct_auto_reply_catalog_and_recommendation_paths_fail_closed_when_capability_disabled(query):
    db = Mock()
    reply = _deterministic_customer_reply(
        db,
        business_id=7,
        conversation_id=11,
        query_text=query,
        workspace_config={"enabled_capabilities": ["CORE_CRM"]},
    )
    assert reply is None
    db.query.assert_not_called()


def test_catalog_selection_does_not_query_product_identity_before_capability_check():
    db = Mock()
    with patch("app.services.auto_reply_service._catalog_request_has_identity_overlap") as identity_lookup:
        reply = _deterministic_customer_reply(
            db,
            business_id=7,
            conversation_id=11,
            query_text="I need a product for oily skin",
            workspace_config={"enabled_capabilities": ["CORE_CRM"]},
        )

    assert reply is None
    identity_lookup.assert_not_called()
    db.query.assert_not_called()


def test_coolant_instruction_does_not_read_catalog_when_retail_capability_is_disabled():
    db = Mock()
    reply = _deterministic_customer_reply(
        db, business_id=7, conversation_id=11,
        query_text="Nước làm mát pha sẵn có cần pha thêm nước không?",
        workspace_config={"enabled_capabilities": ["CORE_CRM"]},
    )

    assert reply is None
    db.query.assert_not_called()


def test_combo_price_shortcut_does_not_query_catalog_when_retail_capability_is_disabled():
    from app.services.product_pricing import combo_price_comparison_reply

    with patch(
        "app.services.product_pricing.combo_price_comparison_reply",
        wraps=combo_price_comparison_reply,
    ) as catalog_lookup:
        reply = _combo_price_comparison_reply_if_allowed(
            Mock(), business_id=7, conversation_id=11,
            text="Tính giá hai sản phẩm này",
            workspace_config={"enabled_capabilities": ["CORE_CRM"]},
        )

    assert reply is None
    catalog_lookup.assert_not_called()


def test_product_image_catalog_paths_require_enabled_retail_capability():
    with patch("app.services.auto_reply_service.settings.RAG_IMAGE_CATALOG_MATCH_ENABLED", True), \
         patch("app.services.auto_reply_service._should_match_image_to_product", return_value=True):
        assert not _catalog_image_matching_allowed(
            {"enabled_capabilities": ["CORE_CRM"]},
            image_bytes=b"image", image_mime_type="image/jpeg", query_text="tìm món trong ảnh",
        )
        assert _catalog_image_matching_allowed(
            _catalog_enabled_workspace_config(),
            image_bytes=b"image", image_mime_type="image/jpeg", query_text="tìm món trong ảnh",
        )


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


def test_rag_skips_auto_reply_while_conversation_waits_for_staff():
    conversation = Mock(bot_mode="auto", resolution_outcome="needs_human")
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = conversation
    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
         patch("app.services.auto_reply_service._latest_inbound_image_url", return_value=None), \
         patch("app.services.auto_reply_service.send_text_reply") as send, \
         patch("app.services.auto_reply_service.retrieve") as retrieve:
        result = process_rag_auto_reply(db, 7, "facebook", "What is the return policy?", 4)
    assert result is False
    assert conversation.bot_mode == "auto"
    send.assert_not_called()
    retrieve.assert_not_called()


def test_delivery_unknown_keeps_bot_enabled_and_notifies_staff_without_retry():
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
    assert conversation.bot_mode == "auto"
    assert conversation.resolution_outcome == "needs_human"
    notify.assert_called_once()


def test_policy_disclosure_uses_idempotent_staff_handoff_recording():
    conversation = Mock(id=7, customer_id=8)
    db = Mock()
    with patch("app.services.auto_reply_service._notify_rag_handoff_required") as notify:
        recorded = _record_rag_handoff(
            db,
            conversation=conversation,
            business_id=4,
            query_text="đổi trả và bảo hành thế nào?",
            reason="missing_warranty_policy_source",
            idempotency_key="turn-1:missing-warranty-policy",
        )

    assert recorded
    notify.assert_called_once_with(
        db,
        conversation=conversation,
        business_id=4,
        query_text="đổi trả và bảo hành thế nào?",
        reason="missing_warranty_policy_source",
        idempotency_key="turn-1:missing-warranty-policy",
    )


def test_rag_handoff_notification_persists_database_idempotency_key():
    from app.services.auto_reply_service import _notify_rag_handoff_required

    conversation = Mock(id=7, customer_id=8, assigned_user_id=None)
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = None
    with patch("app.services.auto_reply_service.manager.is_user_connected", return_value=False), \
         patch("app.services.auto_reply_service.create_notification") as create:
        _notify_rag_handoff_required(
            db,
            conversation=conversation,
            business_id=4,
            query_text="Đổi trả thế nào?",
            reason="no_matching_policy_source",
            idempotency_key="turn-1:handoff:no_matching_policy_source",
        )

    assert create.call_args.kwargs["idempotency_key"] == "turn-1:handoff:no_matching_policy_source"
    db.commit.assert_called_once()


def test_rag_handoff_retry_updates_reason_without_creating_another_notification():
    from types import SimpleNamespace
    from app.services.auto_reply_service import _notify_rag_handoff_required

    existing = SimpleNamespace(
        metadata_={"reason": "no_rag_context", "reasons": ["no_rag_context"]},
        idempotency_key="rag-handoff:turn-1",
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = existing
    conversation = Mock(id=7, customer_id=8, assigned_user_id=None)
    with patch("app.services.auto_reply_service.create_notification") as create:
        _notify_rag_handoff_required(
            db, conversation=conversation, business_id=4, query_text="Question",
            reason="missing_warranty_policy_source", idempotency_key="rag-handoff:turn-1",
        )
    create.assert_not_called()
    assert existing.metadata_["reason"] == "missing_warranty_policy_source"
    assert existing.metadata_["reasons"] == ["no_rag_context", "missing_warranty_policy_source"]
    assert conversation.resolution_outcome == "needs_human"
    db.commit.assert_called_once()


def test_rag_handoff_idempotency_is_stable_across_reason_changes():
    from app.services.auto_reply_service import _rag_handoff_idempotency_key

    assert _rag_handoff_idempotency_key("inbound:42") == "rag-handoff:inbound:42"
    assert _rag_handoff_idempotency_key(None) is None


def test_failed_handoff_recording_is_reported_as_not_queued():
    from app.services.auto_reply_service import _handoff_recording_failed_reply

    reply = _handoff_recording_failed_reply("Tôi muốn hỏi chính sách đổi trả")
    assert "liên hệ trực tiếp" in reply
    assert "nhân viên sẽ kiểm tra" not in reply


def test_handoff_persistence_failure_is_not_reported_as_success():
    conversation = Mock(id=7, customer_id=8)
    db = Mock()
    with patch(
        "app.services.auto_reply_service._notify_rag_handoff_required",
        side_effect=RuntimeError("notification store unavailable"),
    ):
        assert not _record_rag_handoff(
            db,
            conversation=conversation,
            business_id=4,
            query_text="Đổi trả thế nào?",
            reason="no_matching_policy_source",
        )
    db.rollback.assert_called_once()


def test_rag_handoff_duplicate_insert_race_is_treated_as_persisted():
    from sqlalchemy.exc import IntegrityError

    conversation = Mock(id=7, customer_id=8)
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = Mock()
    with patch(
        "app.services.auto_reply_service._notify_rag_handoff_required",
        side_effect=IntegrityError("INSERT", {}, RuntimeError("duplicate key")),
    ):
        assert _record_rag_handoff(
            db,
            conversation=conversation,
            business_id=4,
            query_text="Đổi trả thế nào?",
            reason="no_matching_policy_source",
            idempotency_key="turn-1:handoff:no_matching_policy_source",
        )
    db.rollback.assert_called_once()


def test_provider_echo_proves_delivery_even_if_bridge_response_was_uncertain():
    from app.services.auto_reply_service import _mark_auto_reply_failed
    row = Mock(status="sending", raw_payload={"provider_history_message_id": "mid.123"})
    db = Mock()
    db.query.return_value.filter.return_value.populate_existing.return_value.first.return_value = row
    _mark_auto_reply_failed(db, "turn:1", HTTPException(409, detail={"code": "delivery_unknown"}))
    assert row.status == "sent"
    db.commit.assert_called_once()


def test_staff_decision_retry_does_not_duplicate_notification():
    from app.services.auto_reply_service import _notify_rag_handoff_required
    db=Mock()
    db.query.return_value.filter.return_value.first.return_value=Mock()
    with patch('app.services.auto_reply_service.create_notification') as notify:
        _notify_rag_handoff_required(db,conversation=Mock(id=7,customer_id=8),business_id=4,
            query_text='Question',reason='business_decision_needed',idempotency_key='graph-decision:1')
    notify.assert_not_called()


@pytest.mark.parametrize("mode", ["auto", "human"])
@pytest.mark.parametrize("reason", ["no_rag_context", "no_verified_sales_data", "llm_unavailable"])
def test_staff_alert_preserves_the_users_bot_mode(mode, reason):
    from app.services.auto_reply_service import _notify_rag_handoff_required

    conversation = Mock(id=7, customer_id=8, assigned_user_id=None, bot_mode=mode)
    with patch("app.services.auto_reply_service.create_notification") as notify:
        _notify_rag_handoff_required(Mock(), conversation=conversation, business_id=7, query_text="Sản phẩm gì?", reason=reason)
    assert conversation.bot_mode == mode
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
        stack.enter_context(patch(
            "app.tenancy.workspace_modules.get_workspace_config",
            return_value=_catalog_enabled_workspace_config(),
        ))
        mock("_latest_inbound_image_url", return_value=None)
        mock("customer_order_reply", return_value=None)
        # Exercise the RAG prompt path; the exact-catalog shortcut has its own tests.
        mock("_deterministic_customer_reply", return_value=None)
        mock("_find_exact_product", return_value=(product, "DM-APP-001"))
        mock("find_ambiguous_product_matches", return_value=[])
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


@pytest.mark.parametrize("query", [
    "Giá của XM-NSD-WA110 bao nhiêu?",
    "Gợi ý sản phẩm phù hợp cho tôi",
])
def test_legacy_auto_reply_denies_catalog_and_recommendations_before_retrieval_when_disabled(query):
    db = Mock()
    with patch("app.tenancy.workspace_modules.get_workspace_config", return_value={
        "business_model": "RETAIL",
        "enabled_capabilities": ["CORE_CRM"],
        "available_dependencies": [],
    }), patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
         patch("app.services.auto_reply_service.is_business_open", return_value=True), \
         patch("app.services.auto_reply_service._latest_inbound_image_url", return_value=None), \
         patch("app.services.auto_reply_service.customer_order_reply", return_value=None), \
         patch("app.services.privacy_service.customer_memory_opt_out_reply", return_value=None), \
         patch("app.services.auto_reply_service.retrieve") as retrieve, \
         patch("app.services.auto_reply_service._live_product_context_chunk") as live_catalog, \
         patch("app.services.auto_reply_service.send_text_reply", return_value={"message_id": "denied"}) as send:
        handled = process_rag_auto_reply(
            db, 91, "telegram", query, 7,
        )

    assert handled is True
    retrieve.assert_not_called()
    live_catalog.assert_not_called()
    assert "chưa bật quyền" in send.call_args.kwargs["text"].casefold()


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


def test_delivery_unknown_copy_is_channel_neutral():
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = Mock(status="delivery_unknown")
    with patch("app.services.auto_reply_service._get_conversation_recipient", return_value=("facebook", "customer-1")), \
         patch("app.services.auto_reply_service._claim_auto_reply", return_value=False), \
         patch("app.services.auto_reply_service._send_channel_reply") as send:
        with pytest.raises(HTTPException) as error:
            send_text_reply(db=db, conversation_id=24, channel="facebook", text="Xin chào",
                            business_id=3, auto_reply_key="turn:3:24:1:2")
    assert error.value.detail["code"] == "delivery_unknown"
    assert "kênh này" in error.value.detail["detail"]
    assert "Shopee" not in error.value.detail["detail"]
    send.assert_not_called()


def test_provider_accepted_but_crm_save_failed_is_not_reported_as_send_failure():
    db = Mock()
    with patch("app.services.auto_reply_service._get_conversation_recipient", return_value=("telegram", "user-1")), \
         patch("app.services.auto_reply_service._claim_auto_reply", return_value=True), \
         patch("app.services.auto_reply_service._send_channel_reply", return_value={"message_id": "accepted-1"}) as send, \
         patch("app.services.auto_reply_service._save_auto_reply_outbound", side_effect=RuntimeError("db commit failed")), \
         patch("app.services.auto_reply_service._mark_auto_reply_failed") as mark:
        with pytest.raises(HTTPException) as error:
            send_text_reply(
                db=db, conversation_id=24, channel="telegram", text="Xin chào",
                business_id=3, auto_reply_key="turn:3:24:1:2",
            )
    assert send.call_count == 1
    assert error.value.detail["code"] == "delivery_unknown"
    assert "đã được gửi tới kênh" in error.value.detail["detail"]
    assert mark.call_count == 1
    assert mark.call_args.args[2].detail["code"] == "delivery_unknown"


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
    with patch("app.tenancy.workspace_modules.get_workspace_config", return_value=_catalog_enabled_workspace_config()), patch(
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
    with patch("app.tenancy.workspace_modules.get_workspace_config", return_value=_catalog_enabled_workspace_config()), \
        patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
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
        patch("app.tenancy.workspace_modules.get_workspace_config", return_value={}), \
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


@patch("app.services.auto_reply_service.settings.CHATBOT_GRAPH_ENABLED",False)
def test_instagram_image_is_passed_to_vision_model_and_gets_a_reply():
    db = Mock()
    conversation = Mock(bot_mode="auto", customer_id=8, resolution_outcome=None)
    db.query.return_value.filter.return_value.first.side_effect = [None, conversation]
    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.tenancy.workspace_modules.get_workspace_config", return_value={}), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
        patch("app.services.auto_reply_service._latest_inbound_image_url", return_value="https://scontent.cdninstagram.com/test.jpg"), \
        patch("app.services.auto_reply_service._download_meta_image", return_value=(b"image-bytes", "image/jpeg")), \
        patch("app.services.auto_reply_service.customer_order_reply", return_value=None), \
        patch("app.services.product_pricing.combo_price_comparison_reply", return_value=None), \
        patch("app.services.auto_reply_service.record_explicit_chat_recommendation_decline"), \
        patch("app.services.auto_reply_service._deterministic_customer_reply", return_value=None), \
        patch("app.services.auto_reply_service.is_browsing_request", return_value=False), \
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


@pytest.mark.parametrize('vision_output,valid',[
    ('{"task":"read_information","description":"Ảnh TEST công tơ điện 01220 kWh."}',True),
    ('```json\n{"task":"read_information","description":"Ảnh TEST công tơ điện 01220 kWh."}\n```',True),
    ('Ảnh TEST công tơ điện hiển thị 01220 kWh; đây là số chưa được khách xác nhận.',True),
    ('not json',False),
    ('{"task":"read_information","description":""}',False),
    ('[]',False),
])
def test_image_reading_reaches_guarded_graph_instead_of_legacy_product_routing(vision_output,valid):
    from types import SimpleNamespace
    from app.services.customer_collection_flow import CollectionFlowResult
    db=Mock()
    conversation=SimpleNamespace(id=4,bot_mode="auto",customer_id=8,resolution_outcome=None)
    db.query.return_value.filter.return_value.first.side_effect=[None,conversation]
    with patch("app.services.auto_reply_service.settings.CHATBOT_GRAPH_ENABLED",True), \
         patch("app.tenancy.workspace_modules.get_workspace_config",return_value={}), \
         patch("app.services.auto_reply_service.get_auto_reply_enabled",return_value=True), \
         patch("app.services.auto_reply_service.is_business_open",return_value=True), \
         patch("app.services.auto_reply_service._latest_inbound_image_url",return_value="https://scontent.fbcdn.net/test.png"), \
         patch("app.services.auto_reply_service._download_meta_image",return_value=(b"image-bytes","image/png")), \
         patch("app.services.privacy_service.customer_memory_opt_out_reply",return_value=None), \
         patch("app.services.auto_reply_service.record_quota_usage"), \
         patch("app.services.auto_reply_service.call_llm_with_image",return_value=vision_output), \
         patch("app.services.conversation_graph.graph_reply",return_value=CollectionFlowResult(session_id=0,status="graph_answer",current_field=None,prompt="Mình đọc 1220 kWh; bạn xác nhận lại giúp mình nhé.")) as graph, \
         patch("app.services.auto_reply_service.send_text_reply",return_value={"message_id":"test"}) as send, \
         patch("app.services.auto_reply_service.retrieve") as legacy:
        assert process_rag_auto_reply(db=db,conversation_id=4,channel="facebook",query_text="Đọc công tơ giúp mình",business_id=1)
    if valid:
        assert "01220 kWh" in graph.call_args.kwargs["query"]
        assert "unverified customer image" in graph.call_args.kwargs["query"]
        assert "xác nhận" in send.call_args.kwargs["text"]
    else:
        graph.assert_not_called()
        assert "chưa đọc chắc chắn" in send.call_args.kwargs["text"]
    legacy.assert_not_called()


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
    with patch("app.tenancy.workspace_modules.get_workspace_config", return_value=_catalog_enabled_workspace_config()), \
        patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
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


def test_rental_catalog_uses_current_available_stock():
    room = Mock()
    room.name = "Phòng trọ 01"
    room.price = 3000000
    room.stock_quantity = 0
    room.reserved_quantity = 0
    room.metadata_ = {"attributes": {"category": ["Phòng trọ"]}}

    assert _is_product_catalog_listing_request("Bạn có những phòng nào vậy? Tư vấn cho tôi được không")
    reply = format_product_catalog_reply([room])
    assert "Mình có các phòng trọ sau:" in reply
    assert "Phòng trọ 01 — 3.000.000 đồng/tháng (không còn trống)" in reply
    assert "hết hàng" not in reply


def test_business_offering_question_uses_live_catalog_instead_of_no_context():
    assert _is_product_catalog_listing_request(
        "Tôi đang muốn biết doanh\nNghiệp của bạn\nKinh doanh gì"
    )
    assert _is_product_catalog_listing_request("Shop của bạn kinh doanh gì?")
    assert not _is_product_catalog_listing_request("Doanh thu kinh doanh tháng này là bao nhiêu?")


def test_room_catalog_with_price_bypasses_exact_product_lookup():
    query = "hiện shop có những phòng trọ nào và giá mỗi phòng bap nhiêu"
    assert _is_product_catalog_listing_request(query)
    assert not _is_product_catalog_listing_request("Phòng trọ 05 giá bao nhiêu?")

    db = Mock()
    with patch("app.tenancy.workspace_modules.get_workspace_config", return_value=_catalog_enabled_workspace_config()), \
        patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
        patch("app.services.auto_reply_service.customer_order_reply", return_value=None), \
        patch("app.services.product_pricing.combo_price_comparison_reply", return_value=None), \
        patch("app.services.auto_reply_service._deterministic_customer_reply", return_value=("Không tìm thấy sản phẩm", "product_not_found")) as exact_lookup, \
        patch("app.services.auto_reply_service.build_product_catalog_reply", return_value="Mình có 11 phòng trọ.") as catalog, \
        patch("app.services.auto_reply_service.send_text_reply") as send:
        assert process_rag_auto_reply(
            db=db, conversation_id=6, channel="facebook", query_text=query, business_id=2,
        ) is True

    exact_lookup.assert_not_called()
    catalog.assert_called_once_with(db, 2, language="vi")
    assert send.call_args.kwargs["text"] == "Mình có 11 phòng trọ."


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
        patch("app.tenancy.workspace_modules.get_workspace_config", return_value=_catalog_enabled_workspace_config()), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
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
        patch("app.tenancy.workspace_modules.get_workspace_config", return_value={
            "business_model": "RETAIL", "enabled_capabilities": ["CORE_CRM"],
            "available_dependencies": [],
        }), \
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


@pytest.mark.parametrize(
    (
        "agentic_mode",
        "expected_retrieval_calls",
        "candidate_similarity",
        "expected_prompt_chunk_ids",
        "expected_retry_would_run",
        "expected_candidate_accepted",
        "expected_retry_selected",
    ),
    [
        ("off", 1, 0.8, [21], False, False, False),
        ("active", 2, 0.8, [22], True, True, True),
        ("decision_shadow", 1, 0.8, [21], True, False, False),
        ("execute_shadow", 2, 0.8, [21], True, True, False),
        ("active", 2, 0.05, [21], True, False, False),
    ],
)
def test_agentic_rag_modes_log_and_preserve_original_hard_filters(
    tmp_path,
    agentic_mode,
    expected_retrieval_calls,
    candidate_similarity,
    expected_prompt_chunk_ids,
    expected_retry_would_run,
    expected_candidate_accepted,
    expected_retry_selected,
):
    from app.rag.agentic_controller import RagRuntimeOptions
    from app.rag.retriever import RetrievedChunk

    db = Mock()
    chunk = RetrievedChunk(
        chunk_id=22, document_id=3,
        content="Chính sách giao hàng: đơn nội thành thường giao trong 1 đến 2 ngày.",
        similarity=candidate_similarity, metadata={}, filename="Chinh sach giao hang",
    )
    weak_chunk = RetrievedChunk(
        chunk_id=21, document_id=3,
        content="Chính sách giao hàng: đơn nội thành thường giao trong 1 đến 2 ngày.",
        similarity=0.1, metadata={}, filename="Chinh sach giao hang",
    )
    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
        patch("app.services.auto_reply_service.customer_order_reply", return_value=None), \
        patch("app.services.auto_reply_service.is_browsing_request", return_value=False), \
        patch("app.services.auto_reply_service._latest_inbound_image_url", return_value=None), \
        patch("app.services.auto_reply_service._contextual_retrieval_query", return_value="Chính sách giao hàng nội thành?"), \
        patch("app.services.auto_reply_service._live_product_context_chunk", return_value=None) as live_catalog, \
        patch("app.services.auto_reply_service.load_rag_runtime_options", return_value=RagRuntimeOptions("bm25", agentic_mode, 4, 0.3, 8)), \
        patch("app.services.auto_reply_service.retrieve", side_effect=[[weak_chunk], [chunk]]) as retrieve, \
        patch("app.services.auto_reply_service.build_agent_memory", return_value={"history": []}), \
        patch("app.services.auto_reply_service.build_prompt", return_value=[{"role": "user", "content": "q"}]) as build_prompt, \
        patch("app.services.auto_reply_service.record_quota_usage"), \
        patch("app.services.auto_reply_service.estimate_ai_cost", return_value=Decimal("0")), \
        patch("app.services.auto_reply_service.call_llm", return_value="Đơn nội thành thường giao trong 1 đến 2 ngày [Nguồn 1]."), \
        patch("app.services.auto_reply_service._get_conversation_recipient", return_value=("telegram", "recipient")), \
        patch("app.services.auto_reply_service._send_channel_reply", return_value={"message_id": "agentic-1"}) as send, \
        patch("app.services.auto_reply_service._save_auto_reply_outbound"), \
        patch("app.services.auto_reply_service.record_explicit_chat_recommendation_decline"), \
        patch("app.services.auto_reply_service._notify_rag_handoff_required") as handoff, \
        patch("app.rag.run_logger.settings.RAG_LOG_FILE", str(tmp_path / "rag.jsonl")):
        result = process_rag_auto_reply(
            db=db, conversation_id=4, channel="telegram",
            query_text="Chính sách giao hàng nội thành?", business_id=1,
        )

    assert result is True
    assert retrieve.call_count == expected_retrieval_calls
    live_catalog.assert_not_called()
    first_filters = retrieve.call_args_list[0].kwargs["hard_filters"]
    if expected_retrieval_calls == 2:
        retry_filters = retrieve.call_args_list[1].kwargs["hard_filters"]
        assert retry_filters == first_filters
    assert all(call.kwargs["retrieval_mode"] == "bm25" for call in retrieve.call_args_list)
    assert all(call.kwargs["enable_ppr"] is False for call in retrieve.call_args_list)
    assert retrieve.call_args_list[0].kwargs["timeout_seconds"] == 8
    if expected_retrieval_calls == 2:
        assert 0 < retrieve.call_args_list[1].kwargs["timeout_seconds"] <= 8
        assert "phí vận chuyển" in retrieve.call_args_list[1].kwargs["query"]
    assert send.called
    handoff.assert_not_called()
    prompt_chunk_ids = [chunk.chunk_id for chunk in build_prompt.call_args.kwargs["chunks"]]
    assert prompt_chunk_ids == expected_prompt_chunk_ids
    log_record = next(
        row for row in map(json.loads, (tmp_path / "rag.jsonl").read_text(encoding="utf-8").splitlines())
        if row.get("operation") == "auto_reply"
    )
    assert log_record["agentic_mode"] == agentic_mode
    assert log_record["agentic_retry_would_run"] is expected_retry_would_run
    assert log_record["agentic_retry_attempted"] is (agentic_mode in {"active", "execute_shadow"})
    assert log_record["agentic_retry_candidate_accepted"] is expected_candidate_accepted
    assert log_record["agentic_retry_selected"] is expected_retry_selected
    assert log_record["agentic_retry_original_chunk_ids"] == [21]
    assert log_record["agentic_retry_candidate_chunk_ids"] == ([22] if expected_retrieval_calls == 2 else [])
