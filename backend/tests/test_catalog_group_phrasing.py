from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.services.catalog_overview import catalog_overview_kind, render_catalog_overview

@pytest.mark.parametrize("query", [
    "cho tôi xem có những loại sản phẩm sữa rửa mặt nào v",
    "tôi đang muốn tìm hiểu nhóm sữa rửa mặt",
    "shop có những loại serum nào",
])
def test_group_browsing_filters_current_catalog(query):
    family = "Serum" if "serum" in query else "Sữa rửa mặt"
    products = [SimpleNamespace(name=family + " dịu nhẹ – " + variant, metadata_={})
                for variant in ["Tiêu chuẩn", "Nhỏ gọn", "Nâng cao", "Bộ đôi"]]
    products.append(SimpleNamespace(name="Toner cấp ẩm", metadata_={}))
    db=Mock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value=products
    assert catalog_overview_kind(query) == "product_group"
    result=render_catalog_overview(db,7,"product_group",query=query)
    assert "4 sản phẩm" in result
    assert all(p.name in result for p in products[:4])
    assert "Toner" not in result


def test_generic_recommendation_asks_needs_instead_of_picking_top_item():
    from app.services.catalog_overview import generic_recommendation_needs_question
    assert generic_recommendation_needs_question("bạn có thể gợi ý sản phẩm phù hợp với nhu cầu của tôi dc ko")
    assert generic_recommendation_needs_question("gợi ý sản phẩm phù hợp với nhu cầu da dầu dưới 200k") is None
    assert generic_recommendation_needs_question("shop có những loại serum nào") is None
