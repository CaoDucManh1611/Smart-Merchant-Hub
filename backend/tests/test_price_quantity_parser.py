from types import SimpleNamespace

import pytest

from app.services.catalog_dialogue import _price_quantity


@pytest.mark.parametrize("query,expected", [
    ("Giá Kem chống nắng SPF 50 bao nhiêu", 0),
    ("Giá 2 chai Kem chống nắng SPF 50 bao nhiêu", 2),
])
def test_product_name_numeral_is_identity_instead_of_quantity(query, expected):
    product = SimpleNamespace(name="Kem chống nắng SPF 50", sku="SUN-A")
    assert _price_quantity(query, [product]) == expected


@pytest.mark.parametrize("quantity", [
    "twenty one bottles",
    "thirty two bottles",
    "minus two bottles",
    "two and three bottles",
    "2 chai và three chai",
    "−2 chai",
    "− 2 chai",
    "–2 chai",
    "-2 chai",
    "2,5 chai",
    "2 hay 3 chai",
    "0 chai",
])
def test_partial_ambiguous_and_invalid_counts_need_clarification(quantity):
    product = SimpleNamespace(name="Gel rửa mặt không hạt 100ml", sku="GEL-100")
    assert _price_quantity(f"Giá {quantity} Gel rửa mặt không hạt 100ml", [product]) is None


def test_bare_price_proposal_is_not_ninety_nine_bottles():
    product = SimpleNamespace(name="Gel rửa mặt không hạt 100ml", sku="GEL-100")
    assert _price_quantity("Giá Gel rửa mặt không hạt 100ml 99?", [product]) is None


@pytest.mark.parametrize("quantity,expected", [("2 chai", 2), ("two bottles", 2), ("", 0)])
def test_single_explicit_count_ignores_capacity(quantity, expected):
    product = SimpleNamespace(name="Gel rửa mặt không hạt 100ml", sku="GEL-100")
    assert _price_quantity(f"Giá {quantity} 100ml Gel rửa mặt không hạt", [product]) == expected
