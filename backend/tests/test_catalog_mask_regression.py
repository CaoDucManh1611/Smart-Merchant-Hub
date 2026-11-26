from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models.sales import Product
from app.models.message import Message
from app.services.product_resolver import resolve_product_mentions
from app.services.catalog_dialogue import catalog_dialogue_reply
from app.services.catalog_overview import render_catalog_overview

def masks(db):
    rows=[]
    for size,price in [(30,79000),(100,189000)]:
        p=Product(business_id=1,sku=f"MASK-{size}",name=f"Mặt nạ đất sét {size}g",price=price,stock_quantity=18,status="active",metadata_={"attributes":{"category":["Mặt nạ đất sét"]}})
        db.add(p);rows.append(p)
    db.commit();return rows

@pytest.mark.parametrize("query",["Cho tôi xem những sản phẩm mặt nạ đi","Nhóm sản phẩm mặt nạ","Hùm cho tôi xem nhóm mặt nạ thử đi có những sản phẩm gì"])
def test_group_returns_both_sizes_even_if_model_picks_one(setup,query):
    db,c,*_=setup;rows=masks(db)
    slots=dict(intent="group",domain="products",group=None,product="Mặt nạ đất sét 100g",budget=None,need=None,reference=True,confidence=.99)
    with patch("app.services.catalog_dialogue._interpret",return_value=slots):
        result=catalog_dialogue_reply(db,1,c,query)
    assert all(p.name in result.prompt for p in rows)

def test_overview_uses_category_not_size(setup):
    db,c,*_=setup;masks(db)
    reply=render_catalog_overview(db,1,"products")
    assert "• Mặt nạ đất sét\n" in reply
    assert "30g" not in reply and "100g" not in reply

@pytest.mark.parametrize("query",["Cho tôi đặt nó đi","Tôi muốn đặt 1 mặt nạ đất sét"])
def test_purchase_keeps_last_100g_instead_of_30g(setup,query):
    db,c,*_=setup;small,large=masks(db)
    db.add(Message(conversation_id=c.id,channel=c.channel,direction="outbound",sender_type="bot",content=f"{large.name}: 189.000 đồng/sản phẩm",metadata_={"catalog_dialogue":{"group":"Mặt nạ đất sét","intent":"detail","shortlist":[large.id]}}));db.commit()
    assert resolve_product_mentions(db,business_id=1,text=query,conversation_id=c.id)==[large]


def test_full_graph_reference_asks_quantity_for_last_mask(setup):
    from app.core.config import settings
    from app.services.conversation_graph import graph_reply
    db,c,*_=setup;small,large=masks(db)
    db.add(Message(conversation_id=c.id,channel=c.channel,direction="outbound",sender_type="bot",content=f"{large.name}: 189.000 đồng/sản phẩm",metadata_={"catalog_dialogue":{"group":"Mặt nạ đất sét","intent":"detail","shortlist":[large.id]}}));db.commit()
    slots=dict(intent="purchase",domain="products",group="Mặt nạ đất sét",product=None,budget=None,need=None,reference=True,confidence=.99)
    with patch.object(settings,"CATALOG_DIALOGUE_ENABLED",True), patch("app.services.catalog_dialogue._interpret",return_value=slots):
        result=graph_reply(db,business_id=1,conversation=c,query="Cho tôi đặt nó đi",job_key="mask-reference")
    assert result.current_field == "quantity"
    result=graph_reply(db,business_id=1,conversation=c,query="1",job_key="mask-quantity")
    assert "100g" in result.prompt and "189.000" in result.prompt
    assert "30g" not in result.prompt


@pytest.mark.parametrize("query", ["Cho xem loại 100g", "Loại 100 g thì sao?", "Cho xem loại100g", "Cho xem mặt nạ đất sét100g"])
def test_size_selection_returns_only_requested_mask(setup, query):
    db, conversation, *_ = setup
    small, large = masks(db)
    db.add(Message(
        conversation_id=conversation.id, channel=conversation.channel,
        direction="outbound", sender_type="bot",
        content=f"{small.name}\n{large.name}",
        metadata_={"catalog_dialogue": {
            "group": "Mặt nạ đất sét", "intent": "group",
            "shortlist": [small.id, large.id],
        }},
    ))
    db.commit()
    meaning = dict(intent="detail", domain="products", group="Mặt nạ đất sét",
                   product=large.name, budget=None, need=None, reference=True, confidence=.99)
    with patch("app.services.catalog_dialogue._interpret", return_value=meaning):
        result = catalog_dialogue_reply(db, 1, conversation, query)
    assert large.name in result.prompt and "189.000" in result.prompt
    assert small.name not in result.prompt
    assert result.metadata["catalog_dialogue"]["shortlist"] == [large.id]


@pytest.mark.parametrize("query,expected_size,expected_price", [
    ("Tôi muốn đặt 1 mặt nạ đất sét", 100, "189.000"),
    ("Tôi muốn đặt 1 mặt nạ đất sét 30g", 30, "79.000"),
])
def test_semantic_purchase_respects_selected_size_and_explicit_change(
    setup, query, expected_size, expected_price,
):
    from app.core.config import settings
    from app.models.sales import Order
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    small, large = masks(db)
    db.add(Message(
        conversation_id=conversation.id, channel=conversation.channel,
        direction="outbound", sender_type="bot",
        content=f"{large.name}: 189.000 đồng/sản phẩm",
        metadata_={"catalog_dialogue": {
            "group": "Mặt nạ đất sét", "intent": "detail", "shortlist": [large.id],
        }},
    ))
    db.commit()
    meaning = dict(intent="purchase", domain="products", group="Mặt nạ đất sét",
                   product="Mặt nạ đất sét", budget=None, need=None, reference=True, confidence=.99)
    with patch.object(settings, "CATALOG_DIALOGUE_ENABLED", True), \
         patch("app.services.catalog_dialogue._interpret", return_value=meaning):
        result = graph_reply(db, business_id=1, conversation=conversation,
                             query=query, job_key=f"mask-selected-{expected_size}")
    assert result.current_field == "order_confirmation"
    assert f"{expected_size}g" in result.prompt and expected_price in result.prompt
    assert (small.name if expected_size == 100 else large.name) not in result.prompt
    assert db.query(Order).count() == 0


def test_full_graph_browse_select_size_then_purchase_keeps_same_sku(setup):
    from app.core.config import settings
    from app.models.sales import Order
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    small, large = masks(db)

    def turn(query, meaning):
        db.add(Message(conversation_id=conversation.id, channel=conversation.channel,
                       direction="inbound", sender_type="customer", content=query))
        db.commit()
        with patch("app.services.catalog_dialogue._interpret", return_value=meaning):
            reply = graph_reply(db, business_id=1, conversation=conversation,
                                query=query, job_key=f"mask-chain-{query}")
        db.add(Message(conversation_id=conversation.id, channel=conversation.channel,
                       direction="outbound", sender_type="bot", content=reply.prompt,
                       metadata_=reply.metadata or {}))
        db.commit()
        return reply

    def meaning(intent, product=None):
        return dict(intent=intent, domain="products", group="Mặt nạ đất sét",
                    product=product, budget=None, need=None, reference=True, confidence=.99)

    with patch.object(settings, "CATALOG_DIALOGUE_ENABLED", True):
        browse = turn("Cho tôi xem những sản phẩm mặt nạ đi", meaning("group", large.name))
        assert small.name in browse.prompt and large.name in browse.prompt
        detail = turn("Cho xem loại 100g", meaning("detail", large.name))
        assert large.name in detail.prompt and small.name not in detail.prompt
        purchase = turn("Cho tôi đặt nó đi", meaning("purchase"))
        assert purchase.current_field == "quantity" and large.name in purchase.prompt
        quote = turn("2", meaning("purchase"))
        assert quote.current_field == "order_confirmation"
        assert large.name in quote.prompt and "378.000" in quote.prompt
        assert small.name not in quote.prompt
    assert db.query(Order).count() == 0


@pytest.mark.parametrize("intent,query", [
    ("detail", "Cho xem loại 200g"),
    ("purchase", "Tôi muốn đặt 1 mặt nạ đất sét 200g"),
    ("detail", "Cho xem loại200g"),
    ("purchase", "Tôi muốn đặt 1 mặt nạ đất sét200g"),
])
def test_unavailable_size_never_falls_back_to_previous_mask(setup, intent, query):
    from app.core.config import settings
    from app.models.customer_collection import CustomerCollectionSession
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    small, large = masks(db)
    db.add(Message(conversation_id=conversation.id, channel=conversation.channel,
                   direction="outbound", sender_type="bot", content=large.name,
                   metadata_={"catalog_dialogue": {
                       "group": "Mặt nạ đất sét", "intent": "detail", "shortlist": [large.id],
                   }}))
    db.commit()
    meaning = dict(intent=intent, domain="products", group="Mặt nạ đất sét",
                   product="Mặt nạ đất sét 200g", budget=None, need=None, reference=True, confidence=.99)
    with patch.object(settings, "CATALOG_DIALOGUE_ENABLED", True), \
         patch("app.services.catalog_dialogue._interpret", return_value=meaning):
        result = graph_reply(db, business_id=1, conversation=conversation,
                             query=query, job_key=f"mask-unavailable-size-{intent}")
    assert result.current_field is None
    assert "chưa" in result.prompt
    assert large.name not in result.prompt and small.name not in result.prompt
    assert db.query(CustomerCollectionSession).count() == 0


@pytest.mark.parametrize("sku,query", [("MASK100G", "Cho xem mã MASK100G"),
                                        ("MASK-100G", "Cho xem mã mask 100g")])
def test_measurement_like_sku_does_not_override_actual_product_size(setup, sku, query):
    db, conversation, *_ = setup
    small, large = masks(db)
    small.sku = sku
    db.commit()
    meaning = dict(intent="detail", domain="products", group="Mặt nạ đất sét",
                   product=small.sku, budget=None, need=None, reference=False, confidence=.99)
    with patch("app.services.catalog_dialogue._interpret", return_value=meaning):
        result = catalog_dialogue_reply(db, 1, conversation, query)
    assert small.name in result.prompt and "79.000" in result.prompt
    assert large.name not in result.prompt
    assert result.metadata["catalog_dialogue"]["shortlist"] == [small.id]


@pytest.mark.parametrize("hint", ["100g", "Mặt nạ đất sét 100g", "Mặt nạ đất sét100g"])
def test_size_only_followup_uses_known_family_when_model_omits_group(setup, hint):
    db, conversation, *_ = setup
    small, large = masks(db)
    db.add(Message(conversation_id=conversation.id, channel=conversation.channel,
                   direction="outbound", sender_type="bot", content=f"{small.name}\n{large.name}",
                   metadata_={"catalog_dialogue": {
                       "group": "Mặt nạ đất sét", "intent": "group",
                       "shortlist": [small.id, large.id],
                   }}))
    db.commit()
    meaning = dict(intent="detail", domain="products", group=None, product=hint,
                   budget=None, need=None, reference=True, confidence=.99)
    with patch("app.services.catalog_dialogue._interpret", return_value=meaning):
        result = catalog_dialogue_reply(db, 1, conversation, "Cho xem loại 100 g")
    assert large.name in result.prompt and small.name not in result.prompt
    assert result.metadata["catalog_dialogue"]["shortlist"] == [large.id]


@pytest.mark.parametrize("query", ["Giá Kem dưỡng da 100g bao nhiêu?", "Giá Kem dưỡng da100g bao nhiêu?"])
def test_current_named_family_overrides_previous_same_size_family(setup, query):
    db, conversation, *_ = setup
    _, large = masks(db)
    cream = Product(business_id=1, sku="CREAM-100", name="Kem dưỡng da 100g",
                    price=219000, stock_quantity=6, status="active",
                    metadata_={"attributes": {"category": ["Kem dưỡng da"]}})
    db.add(cream)
    db.add(Message(conversation_id=conversation.id, channel=conversation.channel,
                   direction="outbound", sender_type="bot", content=large.name,
                   metadata_={"catalog_dialogue": {
                       "group": "Mặt nạ đất sét", "shortlist": [large.id], "intent": "detail",
                   }}))
    db.commit()
    meaning = dict(intent="detail", domain="products", group=None, product=None,
                   budget=None, need=None, reference=True, confidence=.99)
    with patch("app.services.catalog_dialogue._interpret", return_value=meaning):
        result = catalog_dialogue_reply(db, 1, conversation, query)
    assert cream.name in result.prompt and "219.000" in result.prompt
    assert large.name not in result.prompt


def test_same_size_in_different_families_without_context_stays_ambiguous(setup):
    db, conversation, *_ = setup
    masks(db)
    db.add(Product(business_id=1, sku="CREAM-100", name="Kem dưỡng da 100g",
                   price=219000, stock_quantity=6, status="active",
                   metadata_={"attributes": {"category": ["Kem dưỡng da"]}}))
    db.commit()
    meaning = dict(intent="detail", domain="products", group=None, product="100g",
                   budget=None, need=None, reference=False, confidence=.99)
    with patch("app.services.catalog_dialogue._interpret", return_value=meaning):
        result = catalog_dialogue_reply(db, 1, conversation, "Cho xem loại 100g")
    assert "tên hoặc mã" in result.prompt
    assert not result.metadata["catalog_dialogue"]["shortlist"]


def test_same_size_in_one_family_requires_variant_before_checkout(setup):
    from app.core.config import settings
    from app.models.customer_collection import CustomerCollectionSession
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    small, large = masks(db)
    special = Product(business_id=1, sku="MASK-SPECIAL-100", name="Mặt nạ đất sét đặc biệt 100g",
                      price=229000, stock_quantity=6, status="active",
                      metadata_={"attributes": {"category": ["Mặt nạ đất sét"]}})
    db.add(special)
    db.flush()
    db.add(Message(conversation_id=conversation.id, channel=conversation.channel,
                   direction="outbound", sender_type="bot",
                   content=f"{small.name}\n{large.name}\n{special.name}",
                   metadata_={"catalog_dialogue": {
                       "group": "Mặt nạ đất sét", "intent": "group",
                       "shortlist": [small.id, large.id, special.id],
                   }}))
    db.commit()
    meaning = dict(intent="purchase", domain="products", group="Mặt nạ đất sét",
                   product="100g", budget=None, need=None, reference=True, confidence=.99)
    with patch.object(settings, "CATALOG_DIALOGUE_ENABLED", True), \
         patch("app.services.catalog_dialogue._interpret", return_value=meaning):
        result = graph_reply(db, business_id=1, conversation=conversation,
                             query="Đặt 1 loại 100g", job_key="mask-ambiguous-size")
    assert result.current_field is None
    assert large.name in result.prompt and special.name in result.prompt
    assert small.name not in result.prompt
    assert db.query(CustomerCollectionSession).count() == 0
