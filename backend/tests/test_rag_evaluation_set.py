import json
from pathlib import Path


def test_evaluation_set_has_all_core_customer_journeys():
    path = Path(__file__).resolve().parents[2] / "docs" / "chatbot-evaluation-set.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(rows) >= 12
    assert {row["expected_action"] for row in rows} >= {
        "lookup_product",
        "lookup_order",
        "search_knowledge",
        "handoff",
        "clarify_product",
    }
    assert all(row.get("id") and row.get("user") and row.get("intent") for row in rows)

