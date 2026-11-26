from unittest.mock import patch

import pytest

from test_business_request import setup
from test_catalog_price_dialogue_regression import beauty_catalog, remember
from app.services.catalog_dialogue import _price_catalog_scope, catalog_dialogue_reply
from app.services.product_resolver import product_family


@pytest.mark.parametrize("query", [
    "Kem dạng gel giá bao nhiêu",
    "Giá kem dạng gel",
])
def test_cream_modifier_does_not_select_gel_cleanser(beauty_catalog, query):
    db, conversation, rows = beauty_catalog
    with patch("app.services.catalog_dialogue._interpret") as interpret:
        reply = catalog_dialogue_reply(db, 1, conversation, query)
    interpret.assert_not_called()
    assert all(row.name in reply.prompt for row in rows[6:])
    assert all(row.name not in reply.prompt for row in rows[:6])
    assert set(reply.metadata["catalog_dialogue"]["shortlist"]) == {
        row.id for row in rows[6:]
    }


@pytest.mark.parametrize("query,expected", [
    ("Dạng gel giá bao nhiêu", (6, 7)),
    ("Dạng cream giá bao nhiêu", (4, 5)),
])
def test_variant_phrase_narrows_current_cream_families(beauty_catalog, query, expected):
    db, conversation, rows = beauty_catalog
    remember(db, conversation, rows[4:])
    with patch("app.services.catalog_dialogue._interpret") as interpret:
        reply = catalog_dialogue_reply(db, 1, conversation, query)
    interpret.assert_not_called()
    assert set(reply.metadata["catalog_dialogue"]["shortlist"]) == {
        rows[index].id for index in expected
    }
    assert all(row.name not in reply.prompt for index, row in enumerate(rows) if index not in expected)


def test_complete_current_family_overrides_prior_cream_variant(beauty_catalog):
    db, conversation, rows = beauty_catalog
    remember(db, conversation, rows[6:])
    with patch("app.services.catalog_dialogue._interpret") as interpret:
        reply = catalog_dialogue_reply(db, 1, conversation, "Gel rửa mặt không hạt giá bao nhiêu")
    interpret.assert_not_called()
    assert set(reply.metadata["catalog_dialogue"]["shortlist"]) == {rows[2].id, rows[3].id}
    assert all(row.name not in reply.prompt for row in rows[4:])


def test_current_family_head_keeps_all_variants_despite_one_prior_product(beauty_catalog):
    db, conversation, rows = beauty_catalog
    remember(db, conversation, [rows[4]])
    with patch("app.services.catalog_dialogue._interpret") as interpret:
        reply = catalog_dialogue_reply(db, 1, conversation, "Kem giá bao nhiêu")
    interpret.assert_not_called()
    assert set(reply.metadata["catalog_dialogue"]["shortlist"]) == {row.id for row in rows[4:]}


def test_measurement_like_sku_with_space_spelling_keeps_exact_identity(beauty_catalog):
    db, conversation, rows = beauty_catalog
    product = rows[4]
    product.sku = "MASK-100G"
    db.commit()
    with patch("app.services.catalog_dialogue._interpret") as interpret:
        reply = catalog_dialogue_reply(db, 1, conversation, "Giá MASK 100G bao nhiêu")
    interpret.assert_not_called()
    assert product.name in reply.prompt and "149.000" in reply.prompt
    assert reply.metadata["catalog_dialogue"]["shortlist"] == [product.id]


@pytest.mark.parametrize("query", [
    "Kem đánh răng giá bao nhiêu",
    "Giá nước ngọt 100ml bao nhiêu",
    "Kem giá dưới 100000",
    "Giá 2 chai gel rửa mặt không hạt 100ml và phí ship thế nào",
    "Giá 2 chai gel rửa mặt không hạt 100ml có giảm giá không",
    "Kem giá bao nhiêu có phù hợp da dầu không",
])
def test_unknown_nouns_budget_and_policy_keep_their_own_routes(beauty_catalog, query):
    _, _, rows = beauty_catalog
    families = sorted({product_family(row) for row in rows})
    state = {"shortlist": [row.id for row in rows]}
    assert _price_catalog_scope(query, rows, families, state) is None
