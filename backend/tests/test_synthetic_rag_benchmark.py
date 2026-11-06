from scripts import evaluate_synthetic_rag_benchmark as benchmark


def test_synthetic_rag_benchmark_covers_required_scenarios_without_live_services():
    dataset = benchmark.build_dataset()
    assert len(dataset["cases"]) >= 40
    assert dataset["synthetic"] is True
    assert len({case["business_id"] for case in dataset["cases"]}) == 3
    categories = {case["category"] for case in dataset["cases"]}
    assert {
        "product_need", "budget_filter", "product_comparison", "current_price_and_stock",
        "multi_turn_followup", "typo_and_unaccented_query", "similar_product_disambiguation",
        "ambiguous_query", "changed_customer_need", "unsupported_policy_question",
        "anti_hallucination_unknown_item", "cross_tenant_isolation",
        "knowledge_base_prompt_injection", "no_order_or_payment_side_effect",
        "recommendation_respects_live_stock", "out_of_stock_not_recommended",
        "exact_sku_and_variant",
    } <= categories
    assert all(case["expected_evidence_ids"] is not None for case in dataset["cases"])
    private_case = next(case for case in dataset["cases"] if case["category"] == "cross_tenant_isolation")
    assert len(private_case["forbidden_evidence_ids"]) == 1
    assert private_case["forbidden_evidence_ids"][0].split(":", 1)[0] != private_case["business_key"]

    result = benchmark.run_benchmark(dataset)

    assert result["case_count"] == len(dataset["cases"])
    assert result["provider_calls"] == 0
    assert result["tenant_isolation_violation_count"] == 0
    assert result["forbidden_evidence_hit_count"] == 0
    assert result["answer_grounding"].startswith("NOT_MEASURED")
    assert result["answer_correctness"].startswith("NOT_MEASURED")
    assert result["unsupported_answer_claims"].startswith("NOT_MEASURED")
    assert 0 <= result["retrieval_relevant_case_rate_at_k"] <= 1
    assert 0 <= result["mean_evidence_recall_at_k"] <= 1
    assert 0 <= result["mrr_at_k"] <= 1
    unknown_item_rows = [
        row for row in result["cases"]
        if row["category"] == "anti_hallucination_unknown_item"
    ]
    assert len(unknown_item_rows) == 3
    assert all(row["retrieved_evidence_ids"] == [] for row in unknown_item_rows)
    assert result["empty_result_accuracy"] == 1.0
