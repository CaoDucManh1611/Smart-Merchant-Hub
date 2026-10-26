from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import patch

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
    _is_product_attribute_question,
    _is_product_catalog_listing_request,
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
    assert not auto_reply_service._is_recommendation_question("serum01 còn hàng không?")
    reply = _deterministic_customer_reply(
        _db(), business_id=1, conversation_id=1, query_text="serun01 còn hàng không?"
    )

    assert reply is not None
    text, route = reply
    assert route == "product_not_found"
    assert text == PRODUCT_NOT_FOUND_REPLY


def test_numbered_rental_room_matches_without_leading_zero():
    rooms = _DB([
        SimpleNamespace(id=12, name="Phòng trọ 05", sku="TRO-P05", metadata_={"attributes": {"category": ["Phòng trọ"]}}, stock_quantity=1, reserved_quantity=0),
        SimpleNamespace(id=13, name="Phòng trọ 06", sku="TRO-P06", metadata_={"attributes": {"category": ["Phòng trọ"]}}, stock_quantity=1, reserved_quantity=0),
    ])
    product, _ = _find_exact_product(rooms, 2, "phòng 5 ấy, bạn còn phòng không?")
    assert product is rooms.rows[0]


def test_general_room_availability_uses_catalog_count_without_guessing_vacancy():
    rooms = _DB([
        SimpleNamespace(id=12, name="Phòng trọ 05", sku="TRO-P05", metadata_={"attributes": {"category": ["Phòng trọ"]}}, stock_quantity=1, reserved_quantity=0),
        SimpleNamespace(id=13, name="Phòng trọ 06", sku="TRO-P06", metadata_={"attributes": {"category": ["Phòng trọ"]}}, stock_quantity=1, reserved_quantity=0),
    ])
    reply = _deterministic_customer_reply(
        rooms, business_id=2, conversation_id=6, query_text="bạn còn phòng không?",
    )
    assert reply is not None
    assert reply[1] == "rental_availability_current"
    assert "2 phòng trọ" in reply[0]
    assert "theo tồn khả dụng" in reply[0]


def test_longer_unknown_sku_does_not_match_shorter_catalog_sku():
    product, _ = _find_exact_product(_db(), 1, "serum010 còn hàng không?", conversation_id=1)
    assert product is None


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


def test_face_care_request_never_lists_or_personalizes_unrelated_catalog_items():
    query = "Bạn đang có sản phẩm gì về da mặt không?"
    db = _db()
    db.rows[0].description = "Mặt hàng điện gia dụng mẫu 01"
    assert not _is_product_catalog_listing_request(query)

    with patch("app.services.auto_reply_service.serve_recommendations") as serve:
        reply = _recommendation_reply(
            db, business_id=1, customer_id=7, query_text=query,
        )

    assert reply is None
    serve.assert_not_called()


def test_category_catalog_request_without_product_word_lists_catalog():
    query = "Cho tôi xem danh sách đồ điện gia dụng shop đang bán"
    assert auto_reply_service._is_product_catalog_listing_request(query)


def test_generic_clothing_price_question_asks_which_product():
    query = "Chiếc váy này giá bao nhiêu vậy?"
    assert _product_hint(query) == ""
    from app.services.customer_collection_flow import is_browsing_request

    assert not is_browsing_request(query)
    reply = _deterministic_customer_reply(
        _DB([]), business_id=1, conversation_id=1, query_text=query,
    )
    assert reply == (AMBIGUOUS_PRICE_REPLY, "product_price_clarification")


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


def test_live_recommendation_uses_customer_ranking_and_keeps_request_trace():
    recommendation = SimpleNamespace(
        request_id="rec-request-1",
        served_items=[
            {
                "product_id": 17,
                "name": "Túi hồng",
                "price": 129000,
                "available": 4,
                "click_url": "https://crm.example/click/17",
                "reason": "explicit_color_preference",
            }
        ],
    )
    reply_metadata = {}
    db = _DB([])
    with patch("app.services.auto_reply_service.active_recommendation_experiment_id", return_value=8) as experiment, \
         patch("app.services.auto_reply_service.serve_recommendations", return_value=recommendation) as serve:
        reply = _recommendation_reply(
            db,
            business_id=3,
            customer_id=9,
            source_channel="instagram",
            query_text="Shop có đồ màu hồng không?",
            reply_metadata=reply_metadata,
        )

    assert reply is not None
    assert "Túi hồng" in reply
    assert "Lý do: đúng màu bạn đã chọn" in reply
    assert "https://crm.example/click/17" in reply
    experiment.assert_called_once_with(db, business_id=3)
    payload = serve.call_args.kwargs["payload"]
    assert payload.customer_id == 9
    assert payload.experiment_id == 8
    assert payload.context["source_channel"] == "instagram"
    assert reply_metadata["recommendation"]["request_id"] == "rec-request-1"


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


def test_new_product_type_does_not_inherit_unrelated_product_from_history(monkeypatch):
    product = _db().rows[0]
    resolver_calls = []
    monkeypatch.setattr(
        auto_reply_service,
        "resolve_product",
        lambda *_args, **_kwargs: resolver_calls.append(True) or product,
    )
    query = "Chiếc váy này giá bao nhiêu vậy?"

    retrieval_query = _contextual_retrieval_query(
        _DB([product]),
        business_id=1,
        text=query,
        conversation_id=55,
        conversation_history=[
            {"role": "user", "content": "Điện gia dụng mẫu 01 còn hàng không?"},
            {"role": "assistant", "content": "Còn hàng."},
        ],
    )

    assert retrieval_query == query
    assert resolver_calls == []


def test_product_detail_followup_uses_last_product_instead_of_listing_catalog(monkeypatch):
    product = _db().rows[0]
    query = "Chi tiết của sản phẩm"
    assert _is_product_attribute_question(query)
    assert not _is_product_catalog_listing_request(query)
    assert _product_hint(query) == ""
    monkeypatch.setattr(auto_reply_service, "resolve_product", lambda *_args, **_kwargs: product)

    retrieval_query = _contextual_retrieval_query(
        _DB([product]), business_id=1, text=query, conversation_id=55,
    )

    assert retrieval_query == f"{product.name}\n{query}"


def test_product_detail_request_uses_imported_description_and_attributes():
    product = SimpleNamespace(
        id=5,
        name="Điện gia dụng mẫu 05",
        sku="DH-0255-05",
        description="Sản phẩm demo thuộc nhóm điện gia dụng; gồm máy xay và nồi chiên.",
        price=389000,
        stock_quantity=150,
        reserved_quantity=0,
        status="active",
        metadata_={"attributes": {
            "category": ["Điện gia dụng"],
            "colors": ["đen", "trắng", "xanh nhạt"],
            "sizes": ["S", "M", "L"],
        }},
    )

    reply = _deterministic_customer_reply(
        _DB([product]),
        business_id=1,
        conversation_id=1,
        query_text="Cho tôi biết chi tiết Điện gia dụng mẫu 05",
    )

    assert reply is not None
    text, route = reply
    assert route == "product_detail_catalog"
    assert "gồm máy xay và nồi chiên" in text
    assert "màu shop ghi nhận: đen, trắng, xanh nhạt" in text
    assert "kích thước: S, M, L" in text
    assert "389.000 đồng" in text and "150 sản phẩm" in text
    assert "Bạn muốn lấy số lượng bao nhiêu và nhận hàng ở đâu?" in text
    assert "hỗ trợ tạo đơn nháp" in text


def test_product_detail_does_not_invent_missing_catalog_specifications():
    reply = _deterministic_customer_reply(
        _db(), business_id=1, conversation_id=1,
        query_text="Tôi muốn biết chi tiết điện gia dụng mẫu 01",
    )

    assert reply is not None
    text, route = reply
    assert route == "product_detail_catalog"
    assert "349.000 đồng" in text and "46 sản phẩm" in text
    assert "Bạn muốn lấy số lượng bao nhiêu và nhận hàng ở đâu?" in text
    assert "công suất" not in text


def test_uncertain_platform_delivery_is_not_retried_as_a_second_customer_reply():
    from fastapi import HTTPException

    unknown = HTTPException(status_code=409, detail={"code": "delivery_unknown"})
    assert _is_delivery_unknown_error(unknown)
    assert not _is_delivery_unknown_error(HTTPException(status_code=502, detail="bridge unavailable"))


def test_shared_router_matches_serving_for_catalog_questions_with_prices():
    from app.services.chatbot_router import classify_intent
    for query in (
        "Hiện shop có những phòng trọ nào và giá mỗi phòng bao nhiêu",
        "Shop có những sản phẩm nào và giá bao nhiêu?",
        "What products do you sell?",
    ):
        assert classify_intent(query) == "lookup_product_catalog"
    assert classify_intent("SKU ABC123 giá bao nhiêu?") != "lookup_product_catalog"
    assert classify_intent("Mã SKU SER-100 là sản phẩm gì?") == "lookup_product"
    assert classify_intent("Shop có bán Serun01 không?") == "lookup_product"


def test_short_business_questions_are_not_silently_classified_as_smalltalk():
    for query in ("Còn suất không?", "Gói này gồm gì?", "Điện bao nhiêu?", "Đặt lịch thế nào?"):
        assert not auto_reply_service._is_casual_query(query)
    assert auto_reply_service._is_casual_query("Cảm ơn bạn")


def test_multi_intent_and_handoff_precedence_are_shared_across_industries():
    from app.services.chatbot_router import classify_intent
    assert classify_intent("Tôi muốn gặp nhân viên để hỏi giá sản phẩm") == "handoff"
    assert classify_intent("Shop có sản phẩm gì và phí giao hàng thế nào?") == "search_knowledge"
    assert classify_intent("Chính sách đổi trả của SKU ABC123 thế nào?") == "search_knowledge"
    assert classify_intent("Đặt lịch thế nào?") == "search_knowledge"
    assert classify_intent("Cách thanh toán gói dịch vụ?") == "search_knowledge"


def test_specific_detail_inquiry_never_dumps_catalog():
    for query in ("Tôi muốn tìm hiểu phòng 11", "Tôi muốn tìm hiểu SKU ABC123", "Tell me about model ABC123"):
        assert not _is_product_catalog_listing_request(query)
    assert _is_product_catalog_listing_request("Tôi muốn tìm hiểu danh sách sản phẩm")

def test_rental_attribute_question_does_not_short_circuit_to_price_and_stock():
    room = SimpleNamespace(id=11, name="Phòng trọ 11", sku="P11", price=2000000,
        stock_quantity=1, reserved_quantity=0, status="active",
        description="Có wifi miễn phí", metadata_={"offering_type": "rental"})
    assert _deterministic_customer_reply(_DB([room]), business_id=2, conversation_id=1,
        query_text="Phòng 11 có wifi không?") is None
    chunk = auto_reply_service._live_product_context_chunk(_DB([room]), 2,
        "Phòng 11 có wifi không?", 1)
    assert chunk is not None
    assert "Có wifi miễn phí" in chunk.content


def test_missing_target_and_generic_details_across_industries():
    from app.services.chatbot_router import classify_intent
    for query in ("Còn suất không?", "Gói này gồm gì?"):
        assert classify_intent(query) == "clarify_product"
    for query in ("Tôi muốn tìm hiểu SKU ABC123", "Tell me about model ABC123"):
        assert classify_intent(query) == "lookup_product"


def test_rental_booking_followup_keeps_latest_customer_room_and_live_stock():
    room = SimpleNamespace(id=11, name="Phòng trọ 11", sku="P11", price=2000000,
        stock_quantity=1, reserved_quantity=0, status="active", description="",
        metadata_={"offering_type": "rental"})
    db = _DB([room])
    query = _contextual_retrieval_query(db, 2, "Ok cho tôi thuê phòng đó đi", 1, [
        {"role": "assistant", "content": "Phòng 01 giá 3 triệu, cần xác nhận"},
        {"role": "user", "content": "Tôi muốn xem thông tin về phòng 11"},
        {"role": "assistant", "content": "Phòng 11 còn trống 1"},
    ])
    assert query.startswith("Phòng trọ 11\n")
    chunk = auto_reply_service._live_product_context_chunk(db, 2, query, 1)
    assert chunk.metadata["product_id"] == 11
    assert chunk.metadata["available"] == 1
    assert chunk.metadata["price"] == 2000000
