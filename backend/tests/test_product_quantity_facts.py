from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.auto_reply_service import _format_product_fact_reply


@pytest.fixture
def product():
    return SimpleNamespace(
        name="Gel rửa mặt không hạt 100ml",
        price=Decimal("99000"),
        stock_quantity=24,
        reserved_quantity=0,
        metadata_={},
        description="Gel rửa mặt dùng hằng ngày.",
    )


@pytest.mark.parametrize("query", [
    "gia 2 chai 100ml gel rua mat khong hat",
    "toi dang muon biet gia cua 2 chai 100ml gel rua mat khong hat",
])
def test_price_for_requested_quantity_includes_unit_price_and_total(product, query):
    reply = _format_product_fact_reply(product, query, quantity=2)

    assert product.name in reply
    assert "99.000 đồng/sản phẩm" in reply
    assert "2 sản phẩm là 198.000 đồng" in reply


def test_quantity_price_warns_when_available_stock_is_insufficient(product):
    product.stock_quantity = 5
    product.reserved_quantity = 2

    reply = _format_product_fact_reply(
        product, "gia 4 chai gel rua mat khong hat 100ml", quantity=4,
    )

    assert "4 sản phẩm là 396.000 đồng" in reply
    assert "Hiện chỉ còn 3 sản phẩm" in reply


@pytest.mark.parametrize("quantity", [None, 1])
def test_product_size_alone_keeps_unit_pricing(product, quantity):
    reply = _format_product_fact_reply(
        product, "gia gel rua mat khong hat 100ml bao nhieu", quantity=quantity,
    )

    assert "99.000 đồng" in reply
    assert "198.000" not in reply
    assert "9.900.000" not in reply
    assert "sản phẩm là" not in reply


@pytest.mark.parametrize("query", [
    "tong gia 2 chai gel rua mat khong hat 100ml",
    "2 chai gel rua mat khong hat 100ml thanh tien bao nhieu",
])
def test_explicit_total_price_keeps_existing_behavior(product, query):
    reply = _format_product_fact_reply(product, query, quantity=2)

    assert "99.000 đồng/sản phẩm" in reply
    assert "2 sản phẩm là 198.000 đồng" in reply


def test_english_quantity_price_uses_requested_quantity_and_available_stock(product):
    product.stock_quantity = 3
    product.reserved_quantity = 2

    reply = _format_product_fact_reply(
        product, "price of 2 bottles of 100ml cleansing gel", language="en", quantity=2,
    )

    assert "₫99,000 each" in reply
    assert "2 items total ₫198,000" in reply
    assert "Only 1 are currently available" in reply


def test_product_details_keep_profile_information_and_unit_price(product):
    product.metadata_ = {
        "product_profile": {
            "benefits": ["Làm sạch nhẹ nhàng"],
            "usage": ["Dùng với nước"],
        },
    }

    reply = _format_product_fact_reply(
        product, "chi tiet cong dung va gia 2 chai gel rua mat khong hat", quantity=2,
    )

    assert "99.000 đồng/sản phẩm; còn 24 sản phẩm" in reply
    assert "Làm sạch nhẹ nhàng" in reply
    assert "Dùng với nước" in reply
    assert "198.000" not in reply
