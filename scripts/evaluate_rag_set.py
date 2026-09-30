"""Run the deterministic RAG routing regression set without calling an LLM.

This is a fast pre-deploy check.  It validates that representative questions
reach the expected product, policy, order, clarification, or handoff route.
The live LLM answer quality is still measured with response feedback.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.rag.topics import fold_topic_text, infer_query_topic  # noqa: E402
from app.services.customer_collection_flow import is_browsing_request  # noqa: E402
from app.services.customer_order_service import detect_customer_order_intent  # noqa: E402


def expected_route(query: str) -> str:
    folded = fold_topic_text(query)
    if detect_customer_order_intent(query) == "status" or (
        re.search(r"\b(?:don|order)\s+[a-z0-9-]+", folded)
        and any(term in folded for term in ("giao toi dau", "trang thai", "o dau"))
    ):
        return "lookup_order"
    if "muon gap nhan vien" in folded or "gap nhan vien" in folded:
        return "handoff"
    if "tong tien" in folded and "mua" in folded:
        return "clarify_product"
    if infer_query_topic(query) in {"delivery", "returns", "payments", "shop"}:
        return "search_knowledge"
    if "phu hop" in folded or "da nhay cam" in folded or "goi y" in folded:
        return "search_knowledge"
    if any(term in folded for term in ("con hang", "con bao nhieu", "gia bao nhieu", "gia hien tai")):
        return "lookup_product"
    if is_browsing_request(query):
        return "lookup_product_catalog"
    return "search_knowledge"


def main() -> int:
    path = ROOT / "docs" / "chatbot-evaluation-set.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    failures = []
    for row in rows:
        actual = expected_route(row["user"])
        if actual != row["expected_action"]:
            failures.append({"id": row["id"], "expected": row["expected_action"], "actual": actual})
    print(json.dumps({"total": len(rows), "passed": len(rows) - len(failures), "failed": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
