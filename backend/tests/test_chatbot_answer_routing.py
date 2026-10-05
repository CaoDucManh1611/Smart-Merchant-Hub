from types import SimpleNamespace

from app.services.auto_reply_service import (
    AMBIGUOUS_PRICE_REPLY,
    AMBIGUOUS_STOCK_REPLY,
    NO_DELIVERY_POLICY_REPLY,
    NO_RECOMMENDATION_REPLY,
    NO_RETURN_POLICY_REPLY,
    PRODUCT_NOT_FOUND_REPLY,
    _chunk_supports_policy,
    _contextual_retrieval_query,
    _deterministic_customer_reply,
    _find_exact_product,
    _is_delivery_unknown_error,
    _recommendation_reply,
    _product_hint,
)
import app.services.auto_reply_service as auto_reply_service


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def query(self, *args, **kwargs):
        return _Query(self.rows)


def _db():
    return _DB([
        SimpleNamespace(
            id=1,
            name="Điện gia dụng mẫu 01",
            sku="serum01",
            price=349000,
            stock_quantity=46,
            reserved_quantity=0,
            product_url=None,
            status="active",
            metadata_={},
        ),
    ])


def _recommendation_db():
    return _DB([
        SimpleNamespace(
            id=2,
            name="Kem chống nắng Daily Shield",
            sku="KS-003",
            price=179000,
            stock_quantity=18,
            reserved_quantity=0,
            status="active",
            metadata_={"attributes": {"suitable_for": ["da nhạy cảm", "da dầu"]}},
        ),
    ])


def test_unknown_sku_never_falls_back_to_full_catalogue():
    reply = _deterministic_customer_reply(
        _db(), business_id=1, conversation_id=1, query_text="serun01 còn hàng không?"
    )

    assert reply is not None
    text, route = reply
    assert route == "product_not_found"
    assert text == PRODUCT_NOT_FOUND_REPLY


def test_product_hint_ignores_prefatory_clause():
    hint = _product_hint("Kiểm thử sau khi bật bot: giá bộ dao bếp 5 món là bao nhiêu?")
    assert "bếp" in hint and "Kiểm" not in hint


def test_demo_product_stock_question_uses_full_name_not_mau_b():
    product = SimpleNamespace(
        id=4, name="[DEMO] Bình giữ nhiệt inox 600 ml Mây Nhà", sku="BINH-600",
        price=189000, stock_quantity=38, reserved_quantity=0, status="active", metadata_={},
    )
    question = "Shop cho mình biết mẫu bình giữ nhiệt inox 600 ml Mây Nhà hiện còn không nhé?"
    assert _product_hint(question) != "mẫu b"
    reply = _deterministic_customer_reply(_DB([product]), business_id=1, conversation_id=1, query_text=question)
    assert reply == ("Dạ, [DEMO] Bình giữ nhiệt inox 600 ml Mây Nhà hiện còn 38 sản phẩm ạ.", "product_fact")
    quantity_reply = _deterministic_customer_reply(
        _DB([product]), business_id=1, conversation_id=1,
        query_text="Bình giữ nhiệt inox 600 ml Mây Nhà còn bao nhiêu chiếc ạ?",
    )
    assert quantity_reply == ("Dạ, [DEMO] Bình giữ nhiệt inox 600 ml Mây Nhà hiện còn 38 sản phẩm ạ.", "product_fact")


def test_known_product_price_and_stock_are_read_from_live_catalogue():
    reply = _deterministic_customer_reply(
        _db(), business_id=1, conversation_id=1, query_text="serum01 giá bao nhiêu, còn hàng không?"
    )

    assert reply == ("Dạ, Điện gia dụng mẫu 01 đang có giá 349.000 đồng và hiện còn 46 sản phẩm ạ.", "product_fact")


def test_product_link_question_returns_catalogue_url():
    product = _db().rows[0]
    product.product_url = "https://shop.example/products/appliance-01"

    reply = _deterministic_customer_reply(
        _DB([product]), business_id=1, conversation_id=1,
        query_text="Tôi muốn xem liên kết của sản phẩm điện gia dụng mẫu 01",
    )

    assert reply == (
        "Đây là liên kết của Điện gia dụng mẫu 01: https://shop.example/products/appliance-01",
        "product_link",
    )


def test_product_link_pronoun_followup_resolves_last_mentioned_product(monkeypatch):
    product = _db().rows[0]
    product.product_url = "https://shop.example/products/appliance-01"
    monkeypatch.setattr(auto_reply_service, "resolve_product", lambda *_args, **_kwargs: product)

    reply = _deterministic_customer_reply(
        _DB([product]), business_id=1, conversation_id=55,
        query_text="Tôi muốn xem liên kết của nó",
    )

    assert reply == (
        "Đây là liên kết của Điện gia dụng mẫu 01: https://shop.example/products/appliance-01",
        "product_link",
    )


def test_product_link_request_explains_when_shop_has_not_added_a_url():
    reply = _deterministic_customer_reply(
        _db(), business_id=1, conversation_id=1,
        query_text="Cho mình link Điện gia dụng mẫu 01",
    )

    assert reply == (
        "Shop chưa cập nhật liên kết cho Điện gia dụng mẫu 01. Bạn nhắn shop để được gửi link sản phẩm nhé.",
        "product_link_unavailable",
    )


def test_two_bottle_comparison_reads_both_live_prices_without_guessing():
    products = [
        SimpleNamespace(id=1, name="[DEMO] Bình giữ nhiệt inox 600 ml Mây Nhà", sku="B600",
                        price=189000, stock_quantity=38, reserved_quantity=0, status="active", metadata_={}),
        SimpleNamespace(id=2, name="[DEMO] Bình giữ nhiệt inox 1 lít Mây Nhà", sku="B1000",
                        price=259000, stock_quantity=21, reserved_quantity=0, status="active", metadata_={}),
        SimpleNamespace(id=3, name="[DEMO] Ấm đun siêu tốc 1 lít Mây Nhà", sku="A1000",
                        price=499000, stock_quantity=6, reserved_quantity=0, status="active", metadata_={}),
    ]
    reply = _deterministic_customer_reply(
        _DB(products), business_id=1, conversation_id=1,
        query_text="Shop ơi, so sánh bình giữ nhiệt inox 600 ml và loại 1 lít Mây Nhà: giá mỗi loại bao nhiêu ạ?",
    )
    assert reply is not None
    text, route = reply
    assert route == "product_comparison"
    assert "189.000" in text and "259.000" in text
    assert "Ấm đun" not in text


def test_english_comparison_uses_vietnamese_catalog_capacity_and_english_reply():
    products = [
        SimpleNamespace(id=1, name="Bình giữ nhiệt inox 600 ml Mây Nhà", sku="B600",
                        price=189000, stock_quantity=38, reserved_quantity=0, status="active", metadata_={}),
        SimpleNamespace(id=2, name="Bình giữ nhiệt inox 1 lít Mây Nhà", sku="B1000",
                        price=259000, stock_quantity=21, reserved_quantity=0, status="active", metadata_={}),
    ]
    reply = _deterministic_customer_reply(
        _DB(products), business_id=1, conversation_id=1,
        query_text="Can you compare the 600 ml and 1 litre Mây Nhà insulated bottles? Current prices only.",
    )
    assert reply is not None
    assert reply[1] == "product_comparison"
    assert "189,000" in reply[0] and "259,000" in reply[0]


def test_variant_stock_lookup_does_not_substitute_base_product():
    base = SimpleNamespace(
        id=1, name="Lona jacket", sku="LONA", price=500000,
        stock_quantity=99, reserved_quantity=0, status="active", metadata_={},
    )
    variant = SimpleNamespace(
        id=2, name="Áo khoác Lona màu đen size M", sku="LONA-BLK-M", price=500000,
        stock_quantity=12, reserved_quantity=0, status="active",
        metadata_={"aliases": ["Lona jacket black size M"], "display_names": {"en": "Black Lona Jacket, Size M"}},
    )
    query = "Is the Lona jacket in black, size M, available?"
    reply = _deterministic_customer_reply(
        _DB([base, variant]), business_id=1, conversation_id=1, query_text=query
    )
    assert reply == ("Black Lona Jacket, Size M has 12 units in stock.", "product_fact")

    unmatched = _deterministic_customer_reply(
        _DB([base]), business_id=1, conversation_id=1, query_text=query
    )
    assert unmatched is not None and unmatched[1] == "product_not_found"


def test_ambiguous_total_price_requests_product_name():
    reply = _deterministic_customer_reply(
        _db(), business_id=1, conversation_id=1, query_text="Tôi muốn mua 2 sản phẩm, tổng tiền bao nhiêu?"
    )

    assert reply == (AMBIGUOUS_PRICE_REPLY, "product_price_clarification")


def test_ambiguous_stock_request_asks_for_product_name():
    reply = _deterministic_customer_reply(
        _db(), business_id=1, conversation_id=1, query_text="Còn hàng không?"
    )

    assert reply == (AMBIGUOUS_STOCK_REPLY, "product_stock_clarification")


def test_generic_category_stock_question_does_not_claim_product_is_missing():
    reply = _deterministic_customer_reply(
        _db(),
        business_id=1,
        conversation_id=1,
        query_text="Shop có sản phẩm điện gia dụng nào đang còn hàng không?",
    )

    assert reply == (AMBIGUOUS_STOCK_REPLY, "product_stock_clarification")

    english_reply = _deterministic_customer_reply(
        _db(),
        business_id=1,
        conversation_id=1,
        query_text="What products are available?",
    )
    assert english_reply == (
        "Which product do you mean? Send its name or SKU, and I’ll check the exact stock.",
        "product_stock_clarification",
    )


def test_policy_and_recommendation_routes_are_explicit_when_context_is_missing():
    assert NO_DELIVERY_POLICY_REPLY
    assert NO_RETURN_POLICY_REPLY
    assert NO_RECOMMENDATION_REPLY
    assert not _chunk_supports_policy(
        [SimpleNamespace(content="Điện gia dụng mẫu 01 giá 349.000 đồng")],
        "delivery",
    )
    assert _chunk_supports_policy(
        [SimpleNamespace(content="Shop giao hàng toàn quốc, phí ship tính theo khu vực")],
        "delivery",
    )


def test_recommendation_uses_explicit_product_attributes():
    reply = _deterministic_customer_reply(
        _recommendation_db(),
        business_id=1,
        conversation_id=1,
        query_text="Shop có sản phẩm nào phù hợp với da nhạy cảm không?",
    )

    assert reply is not None
    text, route = reply
    assert route == "product_recommendation"
    assert "Kem chống nắng Daily Shield" in text


def test_need_recommendation_filters_wrong_category_and_budget_first():
    products = [
        SimpleNamespace(
            id=1, name="Bình giữ nhiệt inox 600 ml", description="Giữ nóng, phù hợp mang đi làm",
            sku="BOTTLE-600", price=189000, stock_quantity=8, reserved_quantity=0,
            metadata_={"attributes": {"use_case": ["đi làm"], "temperature": ["giữ nước nóng"]}},
        ),
        SimpleNamespace(
            id=2, name="Ô gấp chống nắng mưa", description="Gọn nhẹ mang đi làm",
            sku="UMBRELLA", price=179000, stock_quantity=12, reserved_quantity=0,
            metadata_={"attributes": {"use_case": ["đi làm"]}},
        ),
        SimpleNamespace(
            id=3, name="Túi giữ nhiệt đựng hộp cơm", description="Mang cơm đi làm",
            sku="LUNCH-BAG", price=149000, stock_quantity=10, reserved_quantity=0,
            metadata_={"attributes": {"use_case": ["đi làm"]}},
        ),
        SimpleNamespace(
            id=4, name="Bình giữ nhiệt 1 lít", description="Giữ nóng",
            sku="BOTTLE-1000", price=259000, stock_quantity=7, reserved_quantity=0,
            metadata_={"attributes": {}},
        ),
    ]
    reply = _recommendation_reply(
        _DB(products), business_id=1,
        query_text="Mình cần bình mang đi làm, nhỏ gọn, giữ nước nóng, ngân sách dưới 200.000 đồng.",
    )

    assert reply is not None
    assert "Bình giữ nhiệt inox 600 ml" in reply
    assert "Ô gấp" not in reply
    assert "Túi giữ nhiệt" not in reply
    assert "Bình giữ nhiệt 1 lít" not in reply


def test_hot_water_need_without_product_noun_recommends_verified_thermos():
    products = [
        SimpleNamespace(id=1, name="[DEMO] Bình giữ nhiệt inox 600 ml Mây Nhà", description="",
                        sku="B600", price=189000, stock_quantity=38, reserved_quantity=0,
                        status="active", metadata_={}),
        SimpleNamespace(id=2, name="[DEMO] Ấm đun siêu tốc 1 lít Mây Nhà", description="",
                        sku="A1000", price=179000, stock_quantity=8, reserved_quantity=0,
                        status="active", metadata_={}),
        SimpleNamespace(id=3, name="[DEMO] Bình nước nhựa Tritan 700 ml Mây Nhà", description="Bình mang đi làm",
                        sku="T700", price=99000, stock_quantity=44, reserved_quantity=0,
                        status="active", metadata_={}),
        SimpleNamespace(id=4, name="[DEMO] Túi giữ nhiệt đựng hộp cơm Mây Nhà", description="Mang đi làm",
                        sku="BAG", price=149000, stock_quantity=22, reserved_quantity=0,
                        status="active", metadata_={}),
    ]
    reply = _deterministic_customer_reply(
        _DB(products), business_id=1, conversation_id=1,
        query_text="Mình cần mang nước nóng đi làm, ngân sách dưới 200 nghìn. Shop có mẫu nào phù hợp không?",
    )
    assert reply is not None
    assert reply[1] == "product_recommendation"
    assert "Bình giữ nhiệt inox 600 ml" in reply[0]
    assert "Ấm đun" not in reply[0]
    assert "Tritan" not in reply[0]
    assert "Túi" not in reply[0]


def test_product_attribute_question_is_not_misclassified_as_unknown_product():
    product = SimpleNamespace(
        id=1, name="[DEMO] Bình giữ nhiệt inox 600 ml Mây Nhà", sku="BINH-600",
        price=189000, stock_quantity=38, reserved_quantity=0, status="active", metadata_={},
    )
    reply = _deterministic_customer_reply(
        _DB([product]),
        business_id=1, conversation_id=1,
        query_text="Bình giữ nhiệt inox 600 ml Mây Nhà giữ nóng được bao nhiêu giờ và có màu hồng không?",
    )

    assert reply is None


def test_attribute_followup_does_not_trigger_full_catalog():
    from app.services.customer_collection_flow import is_browsing_request

    assert not is_browsing_request("Mẫu đó giữ nóng được bao nhiêu giờ, có màu hồng không ạ?")
    assert is_browsing_request("Shop có mẫu nào để mình xem không?")


def test_quantity_total_question_is_a_quote_request():
    from app.services.customer_collection_flow import is_price_quote_request

    assert is_price_quote_request("Đổi thành 3 bình thì tổng tiền bao nhiêu? Vẫn chỉ hỏi giá, chưa đặt hàng.")
    assert is_price_quote_request("Ý mình là 3 bình giữ nhiệt inox 600 ml Mây Nhà, tính tổng giúp mình, không tạo đơn.")


def test_attribute_followup_resolves_product_from_prior_customer_turn(monkeypatch):
    product = SimpleNamespace(
        id=1, name="[DEMO] Bình giữ nhiệt inox 600 ml Mây Nhà", sku="BINH-600",
        price=189000, stock_quantity=38, reserved_quantity=0, status="active", metadata_={},
    )
    monkeypatch.setattr(auto_reply_service, "resolve_product", lambda *_args, **_kwargs: product)

    resolved, hint = _find_exact_product(
        _DB([product]), business_id=1, text="Màu hồng không ạ?", conversation_id=55,
    )

    assert resolved is product
    assert hint == ""

    retrieval_query = _contextual_retrieval_query(
        _DB([product]), business_id=1, text="Màu hồng không ạ?", conversation_id=55,
    )
    assert retrieval_query == f"{product.name}\nMàu hồng không ạ?"


def test_uncertain_platform_delivery_is_not_retried_as_a_second_customer_reply():
    from fastapi import HTTPException

    unknown = HTTPException(status_code=409, detail={"code": "delivery_unknown"})
    assert _is_delivery_unknown_error(unknown)
    assert not _is_delivery_unknown_error(HTTPException(status_code=502, detail="bridge unavailable"))
