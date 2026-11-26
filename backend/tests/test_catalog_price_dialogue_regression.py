from unittest.mock import patch

import pytest

from test_business_request import setup
from app.models.message import Message
from app.models.sales import Order, Product
from app.models.customer_collection import CustomerCollectionSession
from app.services.catalog_dialogue import catalog_dialogue_reply


@pytest.fixture
def beauty_catalog(setup):
    db, conversation, original, *_ = setup
    original.name = "Sữa rửa mặt tạo bọt dịu nhẹ 100ml"
    original.price = 89000
    original.stock_quantity = 24
    original.reserved_quantity = 0
    original.metadata_ = {"attributes": {"category": ["Sữa rửa mặt tạo bọt dịu nhẹ"]}}
    rows = [original]
    for name, family, price in [
        ("Sữa rửa mặt tạo bọt dịu nhẹ 150ml", "Sữa rửa mặt tạo bọt dịu nhẹ", 125000),
        ("Gel rửa mặt không hạt 100ml", "Gel rửa mặt không hạt", 99000),
        ("Gel rửa mặt không hạt 200ml", "Gel rửa mặt không hạt", 179000),
        ("Kem dưỡng ẩm dạng cream 30g", "Kem dưỡng ẩm dạng cream", 149000),
        ("Kem dưỡng ẩm dạng cream 50g", "Kem dưỡng ẩm dạng cream", 219000),
        ("Kem dưỡng ẩm dạng gel 30g", "Kem dưỡng ẩm dạng gel", 139000),
        ("Kem dưỡng ẩm dạng gel 50g", "Kem dưỡng ẩm dạng gel", 199000),
    ]:
        product = Product(
            business_id=1, sku=f"BEAUTY-{len(rows)}", name=name, price=price,
            stock_quantity=24, reserved_quantity=0, status="active",
            metadata_={"attributes": {"category": [family]}},
        )
        db.add(product)
        rows.append(product)
    db.commit()
    return db, conversation, rows


def meaning(intent="detail", group=None, product=None, reference=True):
    return dict(intent=intent, domain="products", group=group, product=product,
                budget=None, need=None, reference=reference, confidence=.99)


def remember(db, conversation, rows, group=None):
    db.add(Message(
        conversation_id=conversation.id, channel=conversation.channel,
        direction="outbound", sender_type="bot",
        content="Shop hiện có các lựa chọn sau:\n" + "\n".join(row.name for row in rows),
        metadata_={"catalog_dialogue": {"intent": "detail", "group": group,
                                        "shortlist": [row.id for row in rows]}},
    ))
    db.commit()


@pytest.mark.parametrize("hint", [None, "Kem"])
def test_short_cream_price_request_never_lists_unrelated_cleansers(beauty_catalog, hint):
    db, conversation, rows = beauty_catalog
    remember(db, conversation, rows)
    with patch("app.services.catalog_dialogue._interpret", return_value=meaning(product=hint)):
        reply = catalog_dialogue_reply(db, 1, conversation, "Kem giá bao nhiêu")
    assert all(row.name in reply.prompt for row in rows[4:])
    assert all(row.name not in reply.prompt for row in rows[:4])
    assert set(reply.metadata["catalog_dialogue"]["shortlist"]) == {row.id for row in rows[4:]}
    assert db.query(CustomerCollectionSession).count() == 0


@pytest.mark.parametrize("intent", ["detail", "group"])
def test_price_followup_filters_capacity_even_when_several_families_remain(beauty_catalog, intent):
    db, conversation, rows = beauty_catalog
    remember(db, conversation, rows[:3])
    with patch("app.services.catalog_dialogue._interpret", return_value=meaning(intent)):
        reply = catalog_dialogue_reply(db, 1, conversation, "Giá 2 chai 100ml là bao nhiêu")
    assert rows[0].name in reply.prompt and rows[2].name in reply.prompt
    assert rows[1].name not in reply.prompt
    assert rows[3].name not in reply.prompt
    assert set(reply.metadata["catalog_dialogue"]["shortlist"]) == {rows[0].id, rows[2].id}
    assert db.query(CustomerCollectionSession).count() == 0


@pytest.mark.parametrize("query", [
    "Giá 2 chai 100ml gel rửa mặt không hạt",
    "Tôi đang muốn biết giá của 2 chai 100ml gel rửa mặt không hạt",
])
def test_two_bottle_price_question_uses_real_unit_price_and_total(beauty_catalog, query):
    db, conversation, rows = beauty_catalog
    remember(db, conversation, rows[:3])
    with patch("app.services.catalog_dialogue._interpret", return_value=meaning(
        group="Gel rửa mặt không hạt", product=rows[2].name,
    )):
        reply = catalog_dialogue_reply(db, 1, conversation, query)
    assert rows[2].name in reply.prompt
    assert "99.000" in reply.prompt and "198.000" in reply.prompt
    assert rows[0].name not in reply.prompt and rows[3].name not in reply.prompt
    assert db.query(Order).count() == 0
    assert db.query(CustomerCollectionSession).count() == 0


def test_known_price_works_without_remote_understanding(beauty_catalog):
    db, conversation, rows = beauty_catalog
    with patch("app.services.catalog_dialogue._interpret", side_effect=AssertionError("no remote call for catalog math")):
        reply = catalog_dialogue_reply(db, 1, conversation, "Giá 2 chai 100ml gel rửa mặt không hạt")
    assert rows[2].name in reply.prompt and "198.000" in reply.prompt
    assert db.query(CustomerCollectionSession).count() == 0


def test_capacity_from_price_followup_does_not_invent_a_different_family(beauty_catalog):
    db, conversation, rows = beauty_catalog
    remember(db, conversation, rows[4:])
    with patch("app.services.catalog_dialogue._interpret", side_effect=AssertionError("known contextual price")):
        reply = catalog_dialogue_reply(db, 1, conversation, "Giá 2 chai 100ml là bao nhiêu")
    assert reply.status == "dialogue_clarify"
    assert "quy cách" in reply.prompt
    assert all(row.name not in reply.prompt for row in rows)
    assert db.query(CustomerCollectionSession).count() == 0


def test_group_size_request_applies_measurement_before_listing(beauty_catalog):
    db, conversation, rows = beauty_catalog
    with patch("app.services.catalog_dialogue._interpret", return_value=meaning(
        "group", group="Gel rửa mặt không hạt",
    )):
        reply = catalog_dialogue_reply(db, 1, conversation, "Cho xem nhóm gel rửa mặt không hạt 100ml")
    assert rows[2].name in reply.prompt and rows[3].name not in reply.prompt


def test_group_size_keeps_matching_variants_across_related_families(beauty_catalog):
    db, conversation, rows = beauty_catalog
    with patch("app.services.catalog_dialogue._interpret", return_value=meaning(
        "group", product="Kem dưỡng ẩm",
    )):
        reply = catalog_dialogue_reply(db, 1, conversation, "Cho xem các loại kem dưỡng ẩm 30g")
    assert rows[4].name in reply.prompt and rows[6].name in reply.prompt
    assert all(row.name not in reply.prompt for row in rows if row not in [rows[4], rows[6]])


def test_full_cream_identity_can_quote_without_remote_understanding(beauty_catalog):
    db, conversation, rows = beauty_catalog
    with patch("app.services.catalog_dialogue._interpret", side_effect=AssertionError("known cream price")):
        reply = catalog_dialogue_reply(db, 1, conversation, "Giá 2 hộp kem dưỡng ẩm dạng cream 30g")
    assert rows[4].name in reply.prompt and "298.000" in reply.prompt


def test_serum_identity_is_not_mistaken_for_a_recommendation(beauty_catalog):
    db, conversation, _ = beauty_catalog
    serum = Product(
        business_id=1, sku="SERUM-15", name="Serum dưỡng ẩm 15ml",
        price=169000, stock_quantity=24, reserved_quantity=0, status="active",
        metadata_={"attributes": {"category": ["Serum dưỡng ẩm"]}},
    )
    db.add(serum)
    db.commit()
    with patch("app.services.catalog_dialogue._interpret", side_effect=AssertionError("known Serum price")):
        reply = catalog_dialogue_reply(db, 1, conversation, "Serum dưỡng ẩm 15ml giá bao nhiêu")
    assert serum.name in reply.prompt and "169.000" in reply.prompt


def test_current_cream_question_takes_precedence_over_stale_cleanser_hint(beauty_catalog):
    db, conversation, rows = beauty_catalog
    remember(db, conversation, rows[:3], group="Sữa rửa mặt tạo bọt dịu nhẹ")
    with patch("app.services.catalog_dialogue._interpret", return_value=meaning(
        group="Sữa rửa mặt tạo bọt dịu nhẹ", product=rows[0].name, reference=False,
    )) as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, "Kem giá bao nhiêu")
    remote.assert_not_called()
    assert all(row.name in reply.prompt for row in rows[4:])
    assert all(row.name not in reply.prompt for row in rows[:4])


@pytest.mark.parametrize("query,domain,product", [
    ("Phí giao hàng cho gel rửa mặt không hạt giá bao nhiêu", "knowledge", None),
    ("Gel rửa mặt không hạt 100ml giảm giá bao nhiêu", "knowledge", None),
    ("Giá kem đánh răng bao nhiêu", "products", "Kem đánh răng"),
])
def test_price_words_do_not_turn_policies_or_unknown_products_into_stale_quotes(
    beauty_catalog, query, domain, product,
):
    db, conversation, rows = beauty_catalog
    remember(db, conversation, [rows[2]], group="Gel rửa mặt không hạt")
    slots = meaning(product=product, reference=False)
    slots["domain"] = domain
    with patch("app.services.catalog_dialogue._interpret", return_value=slots) as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, query)
    remote.assert_called_once()
    if domain == "knowledge":
        assert reply is None
    else:
        assert "198.000" not in reply.prompt
        assert all(row.name not in reply.prompt for row in rows)


def test_number_in_exact_sku_is_not_a_bottle_quantity(beauty_catalog):
    db, conversation, rows = beauty_catalog
    with patch("app.services.catalog_dialogue._interpret", side_effect=AssertionError("known SKU price")):
        reply = catalog_dialogue_reply(db, 1, conversation, f"Giá {rows[2].sku} bao nhiêu")
    assert rows[2].name in reply.prompt and "99.000" in reply.prompt
    assert "198.000" not in reply.prompt


def test_measurement_like_sku_keeps_identity_without_remote_understanding(beauty_catalog):
    db, conversation, rows = beauty_catalog
    rows[4].sku = "MASK100G"
    db.commit()
    with patch("app.services.catalog_dialogue._interpret", side_effect=AssertionError("known measurement-like SKU")):
        reply = catalog_dialogue_reply(db, 1, conversation, "Giá MASK100G bao nhiêu")
    assert rows[4].name in reply.prompt and "149.000" in reply.prompt
    assert "quy cách" not in reply.prompt


@pytest.mark.parametrize("query", [
    "Giá 2 hay 3 chai 100ml gel rửa mặt không hạt",
    "Giá -2 chai 100ml gel rửa mặt không hạt",
    "Giá 2,5 chai 100ml gel rửa mặt không hạt",
])
def test_unclear_or_invalid_count_needs_clarification_before_total(beauty_catalog, query):
    db, conversation, rows = beauty_catalog
    with patch("app.services.catalog_dialogue._interpret", return_value=meaning(
        group="Gel rửa mặt không hạt", product=rows[2].name,
    )):
        reply = catalog_dialogue_reply(db, 1, conversation, query)
    assert reply.status == "dialogue_clarify"
    assert "số lượng" in reply.prompt
    assert "198.000" not in reply.prompt
    assert db.query(CustomerCollectionSession).count() == 0
