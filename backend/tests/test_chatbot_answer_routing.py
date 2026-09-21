from types import SimpleNamespace

from app.services.auto_reply_service import (
    AMBIGUOUS_PRICE_REPLY,
    AMBIGUOUS_STOCK_REPLY,
    NO_DELIVERY_POLICY_REPLY,
    NO_RECOMMENDATION_REPLY,
    NO_RETURN_POLICY_REPLY,
    PRODUCT_NOT_FOUND_WITH_HINT,
    _chunk_supports_policy,
    _deterministic_customer_reply,
)


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
    assert text == PRODUCT_NOT_FOUND_WITH_HINT.format(hint="serun01")


def test_known_product_price_and_stock_are_read_from_live_catalogue():
    reply = _deterministic_customer_reply(
        _db(), business_id=1, conversation_id=1, query_text="serum01 giá bao nhiêu, còn hàng không?"
    )

    assert reply == ("Điện gia dụng mẫu 01 hiện có giá 349.000 đồng và còn 46 sản phẩm.", "product_fact")


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
