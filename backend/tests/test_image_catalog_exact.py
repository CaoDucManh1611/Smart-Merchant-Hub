"""No vision provider: verify the bounded SQL projection from an OCR hint."""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from app.services.auto_reply_service import (
    _image_catalog_reply_from_observation,
    _match_customer_image_to_product,
)
from app.services.image_observation_cache import clear_image_observation_cache


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def filter(self, *criteria):
        self.filters.extend(criteria)
        return self

    def limit(self, _n):
        return self

    def order_by(self, *_args):
        return self

    def all(self):
        # The SQL predicates are exercised in the integration suite; this
        # fixture confirms the customer-facing SQL fact formatter.
        return self.rows


class DB:
    def __init__(self, rows):
        self.rows = rows

    def query(self, _model):
        return Query(self.rows)


def test_ocr_code_uses_live_price_stock_and_never_guesses_without_code():
    row = SimpleNamespace(sku="A-01", name="Áo mẫu", price=Decimal("125000"),
                          stock_quantity=5, reserved_quantity=2)
    db = DB([row])
    answer = _image_catalog_reply_from_observation(db, 7, {"visible_sku": "A-01"})
    assert "125.000" in answer and "còn 3" in answer and "xác nhận" in answer
    assert "chưa đọc rõ mã" in _image_catalog_reply_from_observation(db, 7, {"visible_sku": None})
    assert "chưa tìm thấy" in _image_catalog_reply_from_observation(DB([]), 7, {"visible_sku": "A-01"})


def test_image_analysis_cache_skips_second_model_call_but_requeries_catalog(monkeypatch):
    clear_image_observation_cache()
    product = SimpleNamespace(
        id=1, business_id=7, status="active", sku="A-01", name="Áo mẫu",
        description="Áo xanh", metadata_={},
    )
    db = DB([product])
    vision = Mock(return_value="áo màu xanh")
    monkeypatch.setattr("app.services.auto_reply_service.call_llm_with_image", vision)
    monkeypatch.setattr(
        "app.services.auto_reply_service.rank_product_image_candidates",
        lambda products, _description, limit: [SimpleNamespace(product=products[0])],
    )
    monkeypatch.setattr("app.services.auto_reply_service.product_image_url", lambda _product: None)

    first = _match_customer_image_to_product(
        db, business_id=7, image_bytes=b"same-image", image_mime_type="image/png",
    )
    second = _match_customer_image_to_product(
        db, business_id=7, image_bytes=b"same-image", image_mime_type="image/png",
    )

    assert first[0] is second[0] is None
    assert [item.sku for item in second[1]] == ["A-01"]
    assert second[2] == "áo màu xanh"
    assert vision.call_count == 1
