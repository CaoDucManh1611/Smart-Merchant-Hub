"""Grounded product details and variant selections survive provider outages."""
from copy import deepcopy
from unittest.mock import patch

import pytest

from test_business_request import setup
from app.core.config import settings
from app.models.customer_collection import CustomerCollectionSession
from app.models.industry_modules import Appointment
from app.models.message import Message
from app.models.sales import Order, Product
from app.models.ticket import Ticket
from app.services.catalog_dialogue import catalog_dialogue_reply


@pytest.fixture
def toner_catalog(setup):
    db, conversation, *_ = setup
    rows = []
    for sku, name, family, price, business_id, status in [
        ("TONER-100", "Toner dưỡng ẩm 100ml", "Toner dưỡng ẩm", 95000, 1, "active"),
        ("TONER-200", "Toner dưỡng ẩm 200ml", "Toner dưỡng ẩm", 159000, 1, "active"),
        ("CLEANSER-100", "Gel rửa mặt không hạt 100ml", "Gel rửa mặt không hạt", 99000, 1, "active"),
        ("FOREIGN-TONER-100", "Toner dưỡng ẩm 100ml", "Toner dưỡng ẩm", 1000, 2, "active"),
        ("INACTIVE-TONER-100", "Toner dưỡng ẩm 100ml", "Toner dưỡng ẩm", 2000, 1, "inactive"),
    ]:
        product = Product(
            business_id=business_id, sku=sku, name=name, price=price,
            stock_quantity=24, reserved_quantity=2, status=status,
            description="Thông tin sản phẩm do shop ghi nhận.",
            metadata_={"attributes": {"category": [family]}, "product_profile": {
                "category": family, "benefits": ["Thông tin công dụng trong hồ sơ shop"],
                "usage": ["Đối chiếu hướng dẫn trên nhãn trước khi dùng."],
            }},
        )
        db.add(product)
        rows.append(product)
    db.commit()
    return db, conversation, *rows


def commerce_snapshot(db):
    return {
        "orders": db.query(Order).count(),
        "appointments": db.query(Appointment).count(),
        "tickets": db.query(Ticket).count(),
        "collections": db.query(CustomerCollectionSession).count(),
        "inventory": [(p.id, p.stock_quantity, p.reserved_quantity)
                      for p in db.query(Product).order_by(Product.id).all()],
    }


def remember(db, conversation, products, group="Toner dưỡng ẩm"):
    db.add(Message(
        conversation_id=conversation.id, channel=conversation.channel, direction="outbound",
        sender_type="bot", content="Shop có các phiên bản sau:\n" + "\n".join(p.name for p in products),
        metadata_={"catalog_dialogue": {"intent": "detail", "group": group,
                                        "shortlist": [p.id for p in products]}},
    ))
    db.commit()


def meaning(intent="detail", *, domain="products", group="Toner dưỡng ẩm", product=None, reference=False, need=None):
    return dict(intent=intent, domain=domain, group=group, product=product, reference=reference,
                budget=None, need=need, confidence=.99)


def test_exact_toner_detail_conversation_works_with_provider_unavailable(toner_catalog):
    db, conversation, small, large, cleanser, *_ = toner_catalog
    before = commerce_snapshot(db)
    queries = [
        "shop đang bán gì",
        "tôi muốn biết chi tiết Toner dưỡng ẩm",
        "bản 100ml ấy",
        "chi tiết bản toner dưỡng ẩm 100ml ấy",
    ]
    replies = []
    with patch.object(settings, "CATALOG_DIALOGUE_ENABLED", True), \
         patch.object(settings, "SALES_JOURNEY_ENGINE_ENABLED", False), \
         patch("app.services.catalog_dialogue._interpret", side_effect=RuntimeError("provider rate limited")) as remote:
        for query in queries:
            db.add(Message(conversation_id=conversation.id, channel=conversation.channel,
                           direction="inbound", sender_type="customer", content=query))
            db.commit()
            reply = catalog_dialogue_reply(db, 1, conversation, query)
            assert reply is not None
            replies.append(reply)
            db.add(Message(conversation_id=conversation.id, channel=conversation.channel,
                           direction="outbound", sender_type="bot", content=reply.prompt,
                           metadata_=reply.metadata or {}))
            db.commit()
    assert "Toner dưỡng ẩm" in replies[0].prompt
    assert small.name in replies[1].prompt and large.name in replies[1].prompt
    for reply in replies[2:]:
        assert small.name in reply.prompt and "95.000" in reply.prompt
        assert "Thông tin công dụng trong hồ sơ shop" in reply.prompt
        assert large.name not in reply.prompt and cleanser.name not in reply.prompt
        assert reply.metadata["catalog_dialogue"]["shortlist"] == [small.id]
    remote.assert_not_called()
    assert commerce_snapshot(db) == before


@pytest.mark.parametrize("query", [
    "chi tiết bản toner dưỡng ẩm 100ml ấy",
    "tôi muốn biết chi tiết Toner dưỡng ẩm 100ml",
])
def test_explicit_product_detail_needs_no_history_or_provider(toner_catalog, query):
    db, conversation, small, large, cleanser, foreign, inactive = toner_catalog
    before = commerce_snapshot(db)
    with patch("app.services.catalog_dialogue._interpret", side_effect=RuntimeError("provider offline")) as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, query)
    assert reply is not None and small.name in reply.prompt and "95.000" in reply.prompt
    assert "Thông tin công dụng trong hồ sơ shop" in reply.prompt
    assert large.name not in reply.prompt and cleanser.name not in reply.prompt
    assert reply.metadata["catalog_dialogue"]["shortlist"] == [small.id]
    assert foreign.id not in reply.metadata["catalog_dialogue"]["shortlist"]
    assert inactive.id not in reply.metadata["catalog_dialogue"]["shortlist"]
    remote.assert_not_called()
    assert commerce_snapshot(db) == before


@pytest.mark.parametrize("query", ["bản 100ml ấy", "cho xem bản 100 ml"])
def test_capacity_followup_selects_only_current_family_without_provider(toner_catalog, query):
    db, conversation, small, large, cleanser, *_ = toner_catalog
    remember(db, conversation, [small, large])
    before = commerce_snapshot(db)
    with patch("app.services.catalog_dialogue._interpret", side_effect=RuntimeError("provider offline")) as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, query)
    assert reply is not None and small.name in reply.prompt and "95.000" in reply.prompt
    assert large.name not in reply.prompt and cleanser.name not in reply.prompt
    assert reply.metadata["catalog_dialogue"]["shortlist"] == [small.id]
    remote.assert_not_called()
    assert commerce_snapshot(db) == before


def test_unavailable_capacity_does_not_replace_requested_variant(toner_catalog):
    db, conversation, small, large, *_ = toner_catalog
    remember(db, conversation, [small, large])
    before = commerce_snapshot(db)
    with patch("app.services.catalog_dialogue._interpret", side_effect=RuntimeError("provider offline")) as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, "bản 300ml ấy")
    assert reply is not None and reply.status == "dialogue_clarify"
    assert "quy cách" in reply.prompt and "chưa" in reply.prompt
    assert small.name not in reply.prompt and large.name not in reply.prompt
    assert not reply.metadata["catalog_dialogue"]["shortlist"]
    remote.assert_not_called()
    assert commerce_snapshot(db) == before


def test_size_without_family_context_never_selects_arbitrary_product(toner_catalog):
    db, conversation, *_ = toner_catalog
    before = commerce_snapshot(db)
    with patch("app.services.catalog_dialogue._interpret", side_effect=RuntimeError("provider offline")):
        reply = catalog_dialogue_reply(db, 1, conversation, "bản 100ml ấy")
    assert reply is None or not (reply.metadata or {}).get("catalog_dialogue", {}).get("shortlist")
    assert commerce_snapshot(db) == before


def test_explicit_different_family_overrides_previous_toner_list(toner_catalog):
    db, conversation, small, large, cleanser, *_ = toner_catalog
    remember(db, conversation, [small, large])
    before = commerce_snapshot(db)
    with patch("app.services.catalog_dialogue._interpret", side_effect=RuntimeError("provider offline")) as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, "chi tiết Gel rửa mặt không hạt 100ml")
    assert reply is not None and cleanser.name in reply.prompt and "99.000" in reply.prompt
    assert small.name not in reply.prompt and large.name not in reply.prompt
    assert reply.metadata["catalog_dialogue"]["shortlist"] == [cleanser.id]
    remote.assert_not_called()
    assert commerce_snapshot(db) == before


@pytest.mark.parametrize("query,slots,expected_status", [
    ("chi tiết kem đánh răng 100ml ấy", meaning(group=None, product="kem đánh răng"), "catalog_dialogue"),
    ("chi tiết phí giao hàng Toner dưỡng ẩm 100ml", meaning("other", domain="knowledge"), None),
    ("chi tiết cách dùng Toner dưỡng ẩm 100ml", meaning("usage", product="Toner dưỡng ẩm 100ml"), "catalog_dialogue"),
    ("chi tiết Toner dưỡng ẩm 100ml có phù hợp da nhạy cảm không", meaning("recommend", need="da nhạy cảm"), "catalog_dialogue"),
    ("chi tiết đơn hàng Toner dưỡng ẩm 100ml", meaning("other", domain="orders"), None),
    ("chi tiết Toner dưỡng ẩm 100ml, chốt đơn luôn", meaning("purchase", product="Toner dưỡng ẩm 100ml"), None),
])
def test_detail_words_do_not_override_another_intent(toner_catalog, query, slots, expected_status):
    db, conversation, small, large, *_ = toner_catalog
    remember(db, conversation, [small, large])
    before = commerce_snapshot(db)
    with patch("app.services.catalog_dialogue._interpret", return_value=slots) as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, query)
    remote.assert_called_once()
    if expected_status is None:
        assert reply is None
    else:
        assert reply is not None and reply.status == expected_status
        assert "95.000" not in reply.prompt
        assert "Thông tin công dụng trong hồ sơ shop" not in reply.prompt
    assert commerce_snapshot(db) == before


def test_detail_word_does_not_swallow_human_handoff(toner_catalog):
    db, conversation, small, large, *_ = toner_catalog
    remember(db, conversation, [small, large])
    before = commerce_snapshot(db)
    with patch("app.services.catalog_dialogue._interpret", return_value=meaning("handoff")) as remote, \
         patch("app.services.chatbot_agent.execute_chatbot_tool", return_value={"accepted": False}) as handoff:
        reply = catalog_dialogue_reply(db, 1, conversation, "tôi muốn gặp nhân viên hỏi chi tiết Toner dưỡng ẩm 100ml")
    assert reply is not None and reply.status == "dialogue_handoff_failed"
    remote.assert_called_once()
    handoff.assert_called_once()
    assert "95.000" not in reply.prompt
    assert commerce_snapshot(db) == before


@pytest.mark.parametrize("query", [
    "chi tiết Toner dưỡng ẩm, Gel rửa mặt không hạt",
    "chi tiết Gel rửa mặt không hạt 100ml, Toner dưỡng ẩm",
    "chi tiết Toner dưỡng ẩm 100ml, Gel rửa mặt không hạt 100ml",
])
def test_multiple_explicit_families_keep_semantic_understanding(toner_catalog, query):
    db, conversation, small, large, cleanser, *_ = toner_catalog
    before = commerce_snapshot(db)
    with patch("app.services.catalog_dialogue._interpret", return_value=meaning(group=None)) as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, query)
    remote.assert_called_once()
    assert reply is not None
    assert small.name in reply.prompt and cleanser.name in reply.prompt
    assert commerce_snapshot(db) == before


@pytest.mark.parametrize("status", ["pending", "partial"])
@pytest.mark.parametrize("query", ["bản 100ml ấy", "chi tiết bản toner dưỡng ẩm 100ml ấy"])
def test_detail_shortcut_preserves_pending_collection(toner_catalog, status, query):
    db, conversation, small, large, *_ = toner_catalog
    remember(db, conversation, [small, large])
    session = CustomerCollectionSession(
        business_id=1, customer_id=conversation.customer_id, conversation_id=conversation.id,
        purpose="order", status=status, current_field="name", required_fields=["name"],
        collected_fields={"product_id": small.id, "quantity": 1},
    )
    db.add(session)
    db.commit()
    collected = deepcopy(session.collected_fields)
    before = commerce_snapshot(db)
    with patch("app.services.catalog_dialogue._interpret", side_effect=RuntimeError("must retain collection owner")) as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, query)
    assert reply is None
    remote.assert_not_called()
    db.refresh(session)
    assert session.status == status and session.current_field == "name"
    assert session.collected_fields == collected
    assert commerce_snapshot(db) == before
