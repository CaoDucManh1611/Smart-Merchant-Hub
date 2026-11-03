from app.rag.query_expansion import (
    MAX_HYPOTHETICAL_TEXT_CHARS,
    MAX_QUERY_CHARS,
    MAX_QUERY_VARIANTS,
    MAX_VARIANT_CHARS,
    plan_query_expansion,
)


def test_cheap_mode_preserves_original_query_and_filters_without_calling_generator():
    query = "  Có áo size L màu xanh không?  "
    filters = {"required_attributes": {"size": "L", "color": "blue"}, "business_id": 7}

    def unexpected_call(_query):
        raise AssertionError("cheap mode must not invoke the generator")

    plan = plan_query_expansion(query, filters, generator=unexpected_call)

    assert plan.original_query == query
    assert plan.hard_filters is filters
    assert plan.hard_filters == {"required_attributes": {"size": "L", "color": "blue"}, "business_id": 7}
    assert plan.query_variants == ()
    assert plan.hypothetical_text is None
    assert plan.retrieval_queries == (query,)
    assert plan.reason == "cheap_mode"


def test_weak_retrieval_flag_requires_a_boolean():
    try:
        plan_query_expansion(
            "Tìm sản phẩm",
            mode="model",
            weak_retrieval="false",
            generator=lambda _query: {"query_variants": ["other"]},
        )
    except TypeError as error:
        assert str(error) == "weak_retrieval must be a bool"
    else:
        raise AssertionError("truthy strings must not enable an optional model callback")


def test_model_mode_calls_once_after_weak_retrieval_and_bounds_variants():
    query = "Giá serum vitamin C?"
    filters = {"business_id": 1, "required_attributes": {"sku": "SERUM-02"}}
    calls = []

    def generate(received_query):
        calls.append(received_query)
        return {
            "query_variants": [
                "  Giá   serum vitamin C?  ",
                "Serum vitamin C giá bao nhiêu?",
                "Thông tin giá serum",
            ],
            "hypothetical_text": "  Serum vitamin C có giá và tình trạng tồn kho.  ",
        }

    plan = plan_query_expansion(query, filters, mode="model", weak_retrieval=True, generator=generate)

    assert calls == [query]
    assert len(plan.query_variants) == MAX_QUERY_VARIANTS
    assert plan.query_variants == ("Serum vitamin C giá bao nhiêu?", "Thông tin giá serum")
    assert plan.original_query == query
    assert plan.hard_filters is filters
    assert plan.retrieval_queries == (query, *plan.query_variants)
    assert plan.hypothetical_text == "Serum vitamin C có giá và tình trạng tồn kho."
    assert plan.hypothetical_text not in plan.retrieval_queries
    assert plan.hypothetical_text_is_citable is False


def test_model_mode_does_not_call_generator_until_retrieval_is_weak():
    calls = []
    plan = plan_query_expansion(
        "Có còn hàng không?",
        mode="model",
        weak_retrieval=False,
        generator=lambda query: calls.append(query),
    )

    assert calls == []
    assert plan.reason == "retrieval_not_weak"
    assert plan.query_variants == ()


def test_malformed_callback_outputs_fail_closed():
    for malformed in (None, "not-json", ["variant"], {"query_variants": "not-a-list"}):
        plan = plan_query_expansion(
            "Tìm sản phẩm",
            mode="model",
            weak_retrieval=True,
            generator=lambda _query, result=malformed: result,
        )
        assert plan.query_variants == ()
        assert plan.hypothetical_text is None


def test_empty_and_invalid_entries_produce_no_expansions():
    plan = plan_query_expansion(
        "Tìm sản phẩm",
        mode="model",
        weak_retrieval=True,
        generator=lambda _query: {
            "query_variants": ["   ", None, 42],
            "hypothetical_text": " \n ",
        },
    )

    assert plan.query_variants == ()
    assert plan.hypothetical_text is None
    assert plan.reason == "no_valid_expansions"


def test_oversized_generated_text_is_rejected_without_truncation():
    oversized_variant = "x" * (MAX_VARIANT_CHARS + 1)
    oversized_hypothetical = "y" * (MAX_HYPOTHETICAL_TEXT_CHARS + 1)
    plan = plan_query_expansion(
        "Cần sản phẩm nào?",
        mode="model",
        weak_retrieval=True,
        generator=lambda _query: {
            "query_variants": [oversized_variant, "  biến thể hợp lệ  "],
            "hypothetical_text": oversized_hypothetical,
        },
    )

    assert plan.query_variants == ("biến thể hợp lệ",)
    assert plan.hypothetical_text is None
    assert len(plan.query_variants[0]) <= MAX_VARIANT_CHARS


def test_duplicates_are_removed_after_normalization_and_casefolding():
    query = "Áo size L"
    plan = plan_query_expansion(
        query,
        mode="model",
        weak_retrieval=True,
        generator=lambda _query: {
            "query_variants": ["  áo   SIZE l  ", "Áo size L", "Tìm áo cỡ L"],
            "hypothetical_text": "",
        },
    )

    assert plan.query_variants == ("Tìm áo cỡ L",)


def test_original_query_over_limit_is_preserved_and_not_sent_to_generator():
    query = "x" * (MAX_QUERY_CHARS + 1)
    calls = []
    plan = plan_query_expansion(
        query,
        {"required_attributes": {"sku": "SKU-EXACT"}},
        mode="model",
        weak_retrieval=True,
        generator=lambda received: calls.append(received),
    )

    assert calls == []
    assert plan.original_query == query
    assert plan.hard_filters == {"required_attributes": {"sku": "SKU-EXACT"}}
    assert plan.reason == "query_too_long"


def test_generator_exception_is_optional_and_does_not_change_constraints():
    filters = {"business_id": 9, "required_attributes": {"vehicle_model": "Wave Alpha"}}

    def fail(_query):
        raise RuntimeError("provider unavailable")

    plan = plan_query_expansion(
        "Có phụ tùng cho Wave Alpha?",
        filters,
        mode="model",
        weak_retrieval=True,
        generator=fail,
    )

    assert plan.hard_filters is filters
    assert plan.hard_filters["required_attributes"] == {"vehicle_model": "Wave Alpha"}
    assert plan.query_variants == ()
    assert plan.reason == "generator_error"

