import json
from pathlib import Path


def test_evaluation_set_has_all_core_customer_journeys():
    path = Path(__file__).resolve().parents[2] / "docs" / "chatbot-evaluation-set.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(rows) == 80
    assert len({row["id"] for row in rows}) == len(rows)
    assert {row["expected_action"] for row in rows} >= {
        "lookup_product",
        "lookup_order",
        "search_knowledge",
        "handoff",
        "clarify_product",
    }
    assert all(row.get("id") and row.get("user") and row.get("intent") for row in rows)
    assert all("expected_topic" in row and "expected_retrieval_terms" in row for row in rows)
    assert all(isinstance(row["must_include"], list) and isinstance(row["must_not_include"], list) for row in rows)
    category_counts = {}
    for row in rows:
        category_counts[row["category"]] = category_counts.get(row["category"], 0) + 1
    assert len(category_counts) >= 10
    assert min(category_counts.values()) >= 4

