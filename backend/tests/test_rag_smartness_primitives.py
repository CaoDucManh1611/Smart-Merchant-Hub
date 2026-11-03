from app.rag.answer_guard import has_valid_citations
from app.rag.intent_router import build_intent_decision, route_customer_message
from app.rag.lexical import identifiers, query_terms


def test_structured_route_keeps_catalog_query_constraints():
    decision = build_intent_decision(
        "Mã sản phẩm XM-NSD-WA110 dưới 500.000đ còn hàng không?",
        "lookup_product",
    )
    assert decision.intent == "lookup_product"
    assert decision.needs_catalog is True
    assert decision.entities["sku"] == "XM-NSD-WA110"
    assert decision.confidence > 0.8


def test_recommendation_route_records_both_catalog_and_knowledge_needs():
    decision = build_intent_decision(
        "Gợi ý kem chống nắng phù hợp cho tôi",
        "search_knowledge",
        catalog_required=True,
    )
    assert decision.needs_catalog is True
    assert decision.needs_docs is True


def test_live_router_uses_business_rules_and_emits_shop_industry_without_llm():
    decision = route_customer_message(
        "Mã sản phẩm XM-NSD-WA110 còn hàng không?",
        industry="general_retail",
    )
    assert decision.intent == "lookup_product"
    assert decision.industry == "general_retail"
    assert decision.needs_catalog is True


def test_live_router_recognizes_unlabelled_multisegment_sku():
    decision = route_customer_message(
        "DH-1501-126 giá bao nhiêu?",
        industry="general_retail",
    )
    assert decision.entities["sku"] == "DH-1501-126"
    assert decision.needs_catalog is True


def test_vietnamese_synonyms_are_scored_as_alternatives_not_extra_constraints():
    terms = query_terms("shop có kcn, áo phông sz M SKU-ABC-123")
    assert ("sunscreen", "sunblock", "kem chong nang", "kcn") in terms
    assert ("shirt", "shirts", "ao thun", "ao phong") in terms
    assert ("size", "sizes", "sizing", "sz") in terms
    assert "sku-abc-123" in identifiers("SKU-ABC-123")


def test_existing_citation_guard_rejects_unsupported_current_price_and_stock():
    evidence = ["Tên sản phẩm: Bộ nhông sên sên dĩa\nGiá hiện hành: 465000 VND\nTồn khả dụng: 9"]
    assert has_valid_citations(
        "Giá 465.000 đồng, còn 9 sản phẩm [Nguồn 1]",
        evidence,
        authoritative_sources=evidence,
    )
    assert not has_valid_citations(
        "Giá 500.000 đồng, còn 12 sản phẩm [Nguồn 1]",
        evidence,
        authoritative_sources=evidence,
    )
