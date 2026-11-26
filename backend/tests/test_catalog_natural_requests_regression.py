from copy import deepcopy
from unittest.mock import patch

import pytest

from test_business_request import setup
from test_catalog_price_dialogue_regression import beauty_catalog
from app.core.config import settings
from app.models.customer import Customer
from app.models.customer_collection import (
    CustomerAddress, CustomerCollectionSession, CustomerContact, CustomerVerificationChallenge,
)
from app.models.message import Message
from app.models.sales import Order, Product
from app.models.ticket import Ticket
from app.services.catalog_dialogue import _price_catalog_scope, catalog_dialogue_reply
from app.services.conversation_graph import graph_reply
from app.services.customer_collection_flow import advance_customer_collection
from app.services.product_resolver import normalize_product_text, product_family


TONER_NAME = "Toner dưỡng ẩm 200ml"
TONER_GROUP = "Toner dưỡng ẩm"
QUOTE_REQUESTS = [
    "tôi muốn mua 2 toner dưỡng ẩm 200ml giá",
    "tôi muốn mua 2 toner dưỡng ẩm 200ml giá sẽ trả bao nhiêu",
    "tôi muốn mua 2 chai toner dưỡng ẩm 200ml giá bao nhiêu",
]


@pytest.fixture
def natural_catalog(beauty_catalog):
    db, conversation, products = beauty_catalog
    toner = Product(
        business_id=1, sku="NATURAL-TONER-200", name=TONER_NAME,
        price=159000, stock_quantity=24, reserved_quantity=0, status="active",
        metadata_={
            "product_profile": {"category": TONER_GROUP},
            "attributes": {"category": ["Toner", "Dưỡng ẩm"]},
        },
    )
    db.add(toner)
    db.commit()
    return db, conversation, products + [toner], toner


def meaning(intent="detail", *, domain="products", group=None, product=None,
            budget=None, need=None, reference=False):
    return dict(
        intent=intent, domain=domain, group=group, product=product, budget=budget,
        need=need, reference=reference, confidence=.99,
    )


def commerce_snapshot(db):
    return {
        "counts": tuple(db.query(model).count() for model in (
            Order, CustomerCollectionSession, CustomerContact, CustomerAddress,
            CustomerVerificationChallenge, Ticket,
        )),
        "inventory": db.query(
            Product.id, Product.stock_quantity, Product.reserved_quantity,
        ).order_by(Product.id).all(),
        "contacts": db.query(
            Customer.id, Customer.name, Customer.email, Customer.phone, Customer.address,
        ).order_by(Customer.id).all(),
    }


def offline_interpreter():
    return patch(
        "app.services.catalog_dialogue._interpret",
        side_effect=RuntimeError("clear request must work without a provider"),
    )


@pytest.mark.parametrize("query", [
    "bạn đang có sản phẩm gì",
    "bạn đang có sản phẩm nào",
    "shop đang có sản phẩm nào",
])
def test_natural_product_overview_is_grounded_and_local(natural_catalog, query):
    db, conversation, products, _ = natural_catalog
    before = commerce_snapshot(db)

    with offline_interpreter() as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, query)

    assert reply is not None and reply.status == "catalog_dialogue"
    assert all(product.name in reply.prompt or product_family(product) in reply.prompt
               for product in products)
    assert "Không được đọc" not in reply.prompt
    assert "Máy ảnh thử" not in reply.prompt
    remote.assert_not_called()
    assert commerce_snapshot(db) == before


@pytest.mark.parametrize("repeated", [False, True])
def test_natural_group_request_lists_actual_categories_even_when_repeated(natural_catalog, repeated):
    db, conversation, products, _ = natural_catalog
    query = "bạn đang có nhóm sản phẩm nào"
    if repeated:
        db.add_all([
            Message(
                conversation_id=conversation.id, channel=conversation.channel,
                direction="inbound", sender_type="customer", content=query,
            ),
            Message(
                conversation_id=conversation.id, channel=conversation.channel,
                direction="outbound", sender_type="bot",
                content="Bạn muốn mình kiểm tra nhóm hàng, giá hay cách dùng của sản phẩm nào ạ?",
                metadata_={"catalog_dialogue": {"intent": "other", "shortlist": []}},
            ),
        ])
        db.commit()
    before = commerce_snapshot(db)

    with offline_interpreter() as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, query)

    assert reply is not None and reply.status == "catalog_dialogue"
    expected = {label for product in products
                for label in product.metadata_["attributes"]["category"]}
    actual = {line[2:].strip() for line in reply.prompt.splitlines() if line.startswith("• ")}
    assert actual == expected
    assert "Không được đọc" not in reply.prompt
    remote.assert_not_called()
    assert commerce_snapshot(db) == before


@pytest.mark.parametrize("query", QUOTE_REQUESTS)
def test_buy_worded_price_question_quotes_unit_and_total_without_checkout(natural_catalog, query):
    db, conversation, products, toner = natural_catalog
    before = commerce_snapshot(db)

    with offline_interpreter() as remote, patch(
        "app.services.chatbot_agent.execute_chatbot_tool",
    ) as execute_tool:
        reply = catalog_dialogue_reply(db, 1, conversation, query)

    assert reply is not None and reply.status == "catalog_dialogue"
    assert toner.name in reply.prompt
    assert "159.000" in reply.prompt and "318.000" in reply.prompt
    if "sẽ trả" in query:
        assert "tiền hàng" in reply.prompt.lower()
    assert all(product.name not in reply.prompt for product in products if product.id != toner.id)
    assert reply.current_field is None and reply.session_id == 0
    remote.assert_not_called()
    execute_tool.assert_not_called()
    assert commerce_snapshot(db) == before


@pytest.mark.parametrize("query", [
    "tôi muốn mua 2 toner dưỡng ẩm 200ml",
    "tôi muốn mua 2 toner dưỡng ẩm 200ml giá bao nhiêu, chốt đơn luôn",
])
def test_explicit_purchase_keeps_existing_checkout(natural_catalog, query):
    db, conversation, _, toner = natural_catalog
    before = commerce_snapshot(db)

    with patch(
        "app.services.catalog_dialogue._interpret",
        return_value=meaning("purchase", group=TONER_GROUP, product=toner.name),
    ):
        reply = catalog_dialogue_reply(db, 1, conversation, query)

    assert reply is None
    assert commerce_snapshot(db) == before
    checkout = advance_customer_collection(
        db, business_id=1, customer_id=conversation.customer_id,
        conversation_id=conversation.id, source_channel=conversation.channel, text=query,
    )
    assert checkout is not None and checkout.current_field == "order_confirmation"
    session = db.get(CustomerCollectionSession, checkout.session_id)
    assert [(item["product_id"], item["quantity"])
            for item in session.collected_fields["items"]] == [(toner.id, 2)]
    assert "318.000" in checkout.prompt
    assert db.query(Order).count() == 0
    assert db.query(CustomerContact).count() == 0
    assert commerce_snapshot(db)["inventory"] == before["inventory"]


@pytest.mark.parametrize("quantity", ["0", "-2", "2,5", "2 hoặc 3"])
def test_invalid_buy_worded_quote_asks_quantity_without_checkout(natural_catalog, quantity):
    db, conversation, _, toner = natural_catalog
    before = commerce_snapshot(db)
    query = f"tôi muốn mua {quantity} toner dưỡng ẩm 200ml giá bao nhiêu"

    with patch(
        "app.services.catalog_dialogue._interpret",
        return_value=meaning(group=TONER_GROUP, product=toner.name),
    ):
        reply = catalog_dialogue_reply(db, 1, conversation, query)

    assert reply is not None and reply.status == "dialogue_clarify"
    assert "số lượng" in reply.prompt
    assert "318.000" not in reply.prompt
    assert commerce_snapshot(db) == before


def test_childrens_python_code_request_redirects_in_vietnamese_without_provider(natural_catalog):
    db, conversation, _, _ = natural_catalog
    before = commerce_snapshot(db)

    with offline_interpreter() as remote:
        reply = catalog_dialogue_reply(
            db, 1, conversation, "code python cho tôi bài code thiếu nhi đi",
        )

    assert reply is not None and "out_of_scope" in reply.status
    text = normalize_product_text(reply.prompt)
    assert "shop" in text and "ho tro" in text and "san pham" in text
    assert "```" not in reply.prompt and "def " not in reply.prompt
    remote.assert_not_called()
    assert commerce_snapshot(db) == before


@pytest.mark.parametrize("query,language", [("hello", "en"), ("xin chào", "vi")])
def test_greeting_is_local_and_uses_the_current_language(natural_catalog, query, language):
    db, conversation, _, _ = natural_catalog
    before = commerce_snapshot(db)

    with offline_interpreter() as remote, patch.object(
        settings, "CATALOG_DIALOGUE_ENABLED", True,
    ), patch(
        "app.services.catalog_dialogue.catalog_dialogue_reply",
        side_effect=AssertionError("the graph greeting owner must answer first"),
    ) as catalog:
        reply = graph_reply(
            db, business_id=1, conversation=conversation, query=query,
            job_key=f"natural-greeting-{language}",
        )

    assert reply is not None
    assert "unavailable" not in reply.status and "out_of_scope" not in reply.status
    text = normalize_product_text(reply.prompt)
    if language == "en":
        assert any(term in text for term in ("hello", "hi", "welcome"))
        assert "help" in text or "assist" in text
        assert "ban" not in text.split() and "minh" not in text.split()
    else:
        assert "chao" in text and ("ho tro" in text or "giup" in text)
    remote.assert_not_called()
    catalog.assert_not_called()
    assert commerce_snapshot(db) == before


def test_generic_english_product_help_is_local_and_useful(natural_catalog):
    db, conversation, _, _ = natural_catalog
    before = commerce_snapshot(db)

    with offline_interpreter() as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, "please help me find a product")

    assert reply is not None
    assert "unavailable" not in reply.status and "out_of_scope" not in reply.status
    text = normalize_product_text(reply.prompt)
    assert any(term in text for term in ("product", "products", "category", "categories"))
    assert any(term in text for term in ("need", "looking", "budget", "find", "help"))
    assert "?" in reply.prompt
    assert not any(term in text for term in ("ban muon", "minh", "san pham nao"))
    remote.assert_not_called()
    assert commerce_snapshot(db) == before


@pytest.mark.parametrize("query,slots", [
    ("please help me find toner", meaning("group", group=TONER_GROUP)),
    ("please help me find a product named toner", meaning("group", group=TONER_GROUP)),
    ("please help me find a product for dry skin", meaning("recommend", need="dry skin")),
    ("please help me find a product under 200000", meaning("budget", budget=200000)),
    ("please help me find that product", meaning(product=TONER_NAME, reference=True)),
])
def test_generic_help_shortcut_preserves_specific_product_requirements(natural_catalog, query, slots):
    db, conversation, _, toner = natural_catalog
    db.add(Message(
        conversation_id=conversation.id, channel=conversation.channel, direction="outbound",
        sender_type="bot", content=toner.name,
        metadata_={"catalog_dialogue": {"group": TONER_GROUP, "shortlist": [toner.id]}},
    ))
    db.commit()
    before = commerce_snapshot(db)

    with patch(
        "app.services.catalog_dialogue._interpret", return_value=slots,
    ) as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, query)

    remote.assert_called_once()
    assert reply is not None and "out_of_scope" not in reply.status
    assert commerce_snapshot(db) == before


@pytest.mark.parametrize("status", ["pending", "partial"])
@pytest.mark.parametrize("query", [
    "bạn đang có nhóm sản phẩm nào", QUOTE_REQUESTS[0], "hello",
    "please help me find a product", "code python cho tôi bài code thiếu nhi đi",
])
def test_new_local_shortcuts_preserve_pending_collection_ownership(natural_catalog, status, query):
    db, conversation, _, toner = natural_catalog
    session = CustomerCollectionSession(
        business_id=1, customer_id=conversation.customer_id, conversation_id=conversation.id,
        purpose="order", status=status, current_field="name", required_fields=["name"],
        collected_fields={"product_id": toner.id, "quantity": 1},
    )
    db.add(session)
    db.commit()
    collected = deepcopy(session.collected_fields)
    before = commerce_snapshot(db)

    with offline_interpreter() as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, query)

    assert reply is None
    remote.assert_not_called()
    db.refresh(session)
    assert session.status == status and session.current_field == "name"
    assert session.collected_fields == collected
    assert commerce_snapshot(db) == before


@pytest.mark.parametrize("query", [
    "bạn đang có sản phẩm gì, phí giao hàng bao nhiêu?",
    "please help me find a product and tell me the shipping fee",
])
def test_natural_catalog_words_do_not_swallow_mixed_policy_requests(natural_catalog, query):
    db, conversation, _, _ = natural_catalog
    before = commerce_snapshot(db)

    with patch(
        "app.services.catalog_dialogue._interpret", return_value=meaning("other", domain="knowledge"),
    ) as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, query)

    assert reply is None
    remote.assert_called_once()
    assert commerce_snapshot(db) == before


def test_buy_worded_quote_excludes_foreign_and_inactive_matching_toners(natural_catalog):
    db, conversation, _, toner = natural_catalog
    db.add_all([
        Product(
            business_id=2, sku="FOREIGN-TONER", name=TONER_NAME, price=777000,
            stock_quantity=10, reserved_quantity=0, status="active",
        ),
        Product(
            business_id=1, sku="INACTIVE-TONER", name=TONER_NAME, price=888000,
            stock_quantity=10, reserved_quantity=0, status="inactive",
        ),
    ])
    db.commit()
    before = commerce_snapshot(db)

    with offline_interpreter() as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, QUOTE_REQUESTS[0])

    assert reply is not None and reply.status == "catalog_dialogue"
    assert "159.000" in reply.prompt and "318.000" in reply.prompt
    assert "777.000" not in reply.prompt and "888.000" not in reply.prompt
    assert reply.metadata["catalog_dialogue"]["shortlist"] == [toner.id]
    remote.assert_not_called()
    assert commerce_snapshot(db) == before


def test_unknown_tea_price_does_not_reuse_a_previous_toner_quote(natural_catalog):
    db, conversation, products, toner = natural_catalog
    query = "Giá trà bao nhiêu"
    state = {"intent": "detail", "group": TONER_GROUP, "shortlist": [toner.id]}
    db.add(Message(
        conversation_id=conversation.id, channel=conversation.channel, direction="outbound",
        sender_type="bot", content=f"{toner.name}: 159.000 đồng",
        metadata_={"catalog_dialogue": state},
    ))
    db.commit()
    before = commerce_snapshot(db)

    assert _price_catalog_scope(
        query, products, sorted({product_family(product) for product in products}), state,
    ) is None
    with patch(
        "app.services.catalog_dialogue._interpret", return_value=meaning(product="Trà"),
    ) as remote:
        reply = catalog_dialogue_reply(db, 1, conversation, query)

    remote.assert_called_once()
    assert reply is not None
    assert toner.name not in reply.prompt and "159.000" not in reply.prompt
    assert "318.000" not in reply.prompt
    assert commerce_snapshot(db) == before
