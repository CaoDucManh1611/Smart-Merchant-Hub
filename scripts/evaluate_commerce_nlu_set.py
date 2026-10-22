"""Measure the commerce holdout set against the backend's deterministic routes."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.rag.prompt_builder import detect_reply_language  # noqa: E402
from app.services.auto_reply_service import (  # noqa: E402
    _STOCK_TERMS,
    _fold_text,
    _has_any_term,
    _is_price_question,
    _is_product_fact_question,
    _is_specific_product_lookup,
    _requested_variant_tokens,
)
from app.services.chatbot_agent import (  # noqa: E402
    ESCALATION_TERMS,
    _is_neutral_policy_question,
)
from app.services.customer_collection_flow import (  # noqa: E402
    _has_specific_purchase_signal,
    _is_underspecified_purchase_request,
    _fold,
    _is_purchase_history_question,
    is_browsing_request,
    is_greeting,
    is_order_intent,
    is_price_quote_request,
    is_stock_query_request,
)
from app.services.customer_order_service import detect_customer_order_intent  # noqa: E402


def observed_intent(text: str) -> str | None:
    """Call the same deterministic gates used by the inbound message path."""
    if is_greeting(text):
        return "greeting"

    order_intent = detect_customer_order_intent(text)
    if order_intent == "status":
        return "order_status"
    if order_intent == "cancel":
        return "cancel_order"
    if order_intent == "refund":
        return "refund_request"

    if (
        not _is_neutral_policy_question(text)
        and any(term in text.casefold() for term in ESCALATION_TERMS)
    ):
        return "human_handoff"

    folded = _fold(text)
    if _is_purchase_history_question(folded):
        return "recent_purchase_history"
    if _is_underspecified_purchase_request(text):
        return "purchase_request_underspecified"
    if is_price_quote_request(text):
        return "quote_quantity"
    if is_stock_query_request(text) and _requested_variant_tokens(text):
        return "check_variant_stock"
    if is_stock_query_request(text):
        return "check_stock"
    # The production collection flow checks a resolvable named-product purchase
    # before it lets the broader product-discovery route handle the message.
    if _has_specific_purchase_signal(text) and re.search(
        r"\b(?:mau|model|sku|ma)\s+[a-z0-9][a-z0-9-]*\b", _fold_text(text)
    ):
        return "purchase_request"
    if _is_product_fact_question(text) and _requested_variant_tokens(text):
        return "check_variant_stock"
    if _is_product_fact_question(text):
        if _is_price_question(_fold_text(text)):
            return "check_price"
        return "check_stock"
    if is_order_intent(text):
        return "purchase_request"
    if _is_specific_product_lookup(text):
        return "product_detail"
    if is_browsing_request(text):
        return "browse_catalog"
    return None


def main() -> None:
    cases_path = ROOT / "docs" / "commerce-nlu-evaluation-set.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    utterances = [case for case in cases if case["type"] == "utterance"]
    results = []

    for case in utterances:
        actual = observed_intent(case["text"])
        language = detect_reply_language(case["text"])
        expected_language = "en" if case["reply_locale"].startswith("en") else "vi"
        passed = actual == case["expected_intent"] and language == expected_language
        results.append({
            "id": case["id"],
            "expected": case["expected_intent"],
            "actual": actual or "unhandled",
            "language": "pass" if language == expected_language else f"expected {expected_language}, got {language}",
            "result": "pass" if passed else "gap",
        })

    passed = sum(row["result"] == "pass" for row in results)
    print(json.dumps({
        "scope": "production deterministic intent/language gates; no LLM, provider, or live database; dialogue safety is checked by the SQLite test suite",
        "cases_in_set": len(cases),
        "utterances_evaluated": len(utterances),
        "dialogues_safety_tested": sum(case["type"] == "dialogue" for case in cases),
        "passed": passed,
        "language_passed": sum(row["language"] == "pass" for row in results),
        "gaps": [row for row in results if row["result"] != "pass"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
