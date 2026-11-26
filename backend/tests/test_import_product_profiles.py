from types import SimpleNamespace
from app.api.sales import _import_product_profile, _PRODUCT_IMPORT_FIELDS
from app.services.product_profile import matching_need_products, profile_detail_lines
from app.rag.prompt_builder import build_prompt


def test_imported_needs_feed_recommendations_without_description_parsing():
    values = {"category": "Son dưỡng", "benefits": "Dưỡng ẩm môi", "suitable_needs": "môi khô; dưỡng môi", "usage": "Thoa mỏng", "fact_status": "verified"}
    profile = _import_product_profile(values)
    assert profile["fact_status"] == "unverified"
    p = SimpleNamespace(id=1, price=59000, status="active", stock_quantity=2, reserved_quantity=0, metadata_={"product_profile": profile})
    assert matching_need_products([p], "môi khô dưới 100k", 100000) == [p]
    assert matching_need_products([p], "rửa mặt", 100000) == []
    assert matching_need_products([p], "môi khô", 50000) == []
    assert not any("đối chiếu nhãn" in s for s in profile_detail_lines(p))
    assert profile["fact_status"] == "unverified"
    assert _PRODUCT_IMPORT_FIELDS["suitable_needs"] == "suitable_needs"


def test_old_import_does_not_invent_profile():
    assert _import_product_profile({"description": "Dưỡng môi", "category": "Son"}) == {}


def test_system_rules_apply_without_retrieved_document():
    messages = build_prompt("đặt loại đó", [], system_prompt="Trả lời thân thiện")
    rules = messages[0]["content"]
    assert "thiếu số lượng thì hỏi số lượng" in rules
    assert "Không tự tạo hay đổi SKU" in rules
    assert "Không suy diễn thành phần" in rules
