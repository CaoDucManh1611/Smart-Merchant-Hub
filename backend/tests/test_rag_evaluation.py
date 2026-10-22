from app.rag.evaluation import evaluate_predictions


def test_rag_evaluator_reports_action_recall_mrr_and_grounding():
    cases = [
        {
            "id": "product_1",
            "expected_action": "lookup_product",
            "retrieval_required": True,
            "expected_retrieval_terms": ["serum01"],
            "must_not_include": ["còn đúng 99 chai"],
        },
        {
            "id": "policy_1",
            "expected_action": "search_knowledge",
            "retrieval_required": True,
            "expected_retrieval_terms": ["đổi trả"],
            "must_not_include": ["đổi vô thời hạn"],
        },
    ]
    predictions = [
        {
            "id": "product_1",
            "action": "lookup_product",
            "retrieved_contents": ["catalog", "Serum01 có giá niêm yết trong hệ thống"],
            "answer": "Mình sẽ kiểm tra tồn kho Serum01.",
        },
        {
            "id": "policy_1",
            "action": "lookup_product",
            "retrieved_contents": ["chính sách giao hàng"],
            "answer": "Shop hỗ trợ theo chính sách hiện hành.",
        },
    ]

    metrics = evaluate_predictions(cases, predictions, top_k=2)

    assert metrics["case_count"] == 2
    assert metrics["action_accuracy"] == 0.5
    assert metrics["retrieval_recall_at_k"] == 0.5
    assert metrics["mrr"] == 0.25
    assert metrics["grounded_rate"] == 1.0


def test_evaluator_separates_sources_citations_handoffs_and_latency():
    cases = [
        {"id": "product", "expected_action": "lookup_product", "expected_retrieval_terms": ["sku-x"],
         "expected_sources": ["tenant_product_catalog"], "must_include": ["100000"], "must_not_include": ["giá tự đoán"]},
        {"id": "policy", "expected_action": "search_knowledge", "expected_retrieval_terms": ["đổi trả"],
         "expected_sources": ["approved_tenant_returns_warranty_policy"], "must_include": ["đổi trong 7 ngày"],
         "must_not_include": ["đổi vô thời hạn"]},
        {"id": "handoff", "expected_action": "handoff"},
    ]
    predictions = [
        {"id": "product", "action": "lookup_product", "answer": "SKU-X giá 100000 đồng.",
         "retrieved_contents": ["SKU-X giá hiện hành 100000 đồng"], "retrieved_sources": ["tenant_product_catalog"],
         "latency_ms": 12},
        {"id": "policy", "action": "search_knowledge", "answer": "Được đổi trong 7 ngày [Nguồn 1]",
         "retrieved_contents": ["Chính sách: đổi trả trong 7 ngày"],
         "retrieved_sources": ["approved_tenant_returns_warranty_policy"], "latency_ms": 22},
        {"id": "handoff", "action": "handoff", "answer": "Nhân viên sẽ hỗ trợ.", "handoff_required": True,
         "latency_ms": 32, "provider_error": "quota"},
    ]

    metrics = evaluate_predictions(cases, predictions)

    assert metrics["case_count"] == 3
    assert metrics["action_accuracy"] == 1
    assert metrics["expected_source_recall"] == 1
    assert metrics["citation_pass_rate"] == 1
    assert metrics["handoff_precision"] == metrics["handoff_recall"] == 1
    assert metrics["service_error_rate"] == 0.333333
    assert metrics["latency_mean_ms"] == 22
    assert metrics["latency_p95_ms"] == 32
    assert metrics["missing_prediction_count"] == 0


def test_evaluator_normalizes_unicode_sku_dashes_and_narrow_spaces():
    cases = [{
        "id": "formatted-answer",
        "expected_action": "search_knowledge",
        "must_include": ["DM-APP-001", "30.000 đồng"],
        "must_not_include": ["tồn kho chắc chắn"],
    }]
    predictions = [{
        "id": "formatted-answer",
        "action": "search_knowledge",
        "answer": "DM‑APP‑001 còn 30\u202f000 đồng [Nguồn 1]",
        "retrieved_contents": ["DM-APP-001 có giá 30.000 đồng"],
        "retrieved_sources": [],
    }]

    metrics = evaluate_predictions(cases, predictions)

    assert metrics["must_include_term_rate"] == 1
    assert metrics["answer_contract_pass_rate"] == 1
    assert metrics["grounded_rate"] == 1
    assert metrics["cases"][0]["missing_required_terms"] == []
