from app.rag.evaluation import evaluate_predictions


def test_rag_evaluator_reports_action_recall_mrr_and_grounding():
    cases = [
        {
            "id": "product_1",
            "expected_action": "lookup_product",
            "expected_retrieval_terms": ["serum01"],
            "must_not_include": ["còn đúng 99 chai"],
        },
        {
            "id": "policy_1",
            "expected_action": "search_knowledge",
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
