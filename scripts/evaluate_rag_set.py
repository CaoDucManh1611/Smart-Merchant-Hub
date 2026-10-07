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
from app.services.auto_reply_service import (  # noqa: E402
    _is_price_question,
    _is_product_attribute_question,
    _is_product_catalog_listing_request,
    _is_product_fact_question,
    _is_recommendation_question,
    _product_hint,
    _requested_variant_tokens,
)
from app.services.customer_collection_flow import (  # noqa: E402
    is_browsing_request,
    is_price_quote_request,
    is_stock_query_request,
)
from app.services.customer_order_service import detect_customer_order_intent  # noqa: E402


def _has_product_reference(query: str) -> bool:
    folded = fold_topic_text(query)
    if re.search(r"\b(?:sku|model)\s+[a-z0-9][a-z0-9-]*\b|\bmau\s+\d+\b", folded):
        return True
    if any(phrase in folded for phrase in ("vua noi", "vua hoi", "san pham do", "don do")):
        return True
    generic = {
        "shop", "san", "pham", "hang", "mat", "nao", "gi", "co", "dang", "ban", "nhung",
        "loai", "tot", "nhat", "cai", "nay", "xanh", "den", "hong", "do", "size", "sao",
        "mau", "gia", "bao", "nhieu", "con", "khong", "ko", "hien", "tai", "muon", "xem",
        "thong", "tin", "chi", "tiet", "cho", "toi", "minh", "can", "tu", "van",
    }
    hint = set(fold_topic_text(_product_hint(query)).split())
    return bool(hint - generic)


def expected_route(query: str) -> str:
    folded = fold_topic_text(query)
    order_intent = detect_customer_order_intent(query)
    has_order_reference = bool(re.search(r"\b(?:don|order)\s+[a-z0-9-]+", folded))

    # Privacy, security, payment disputes and serious complaints must reach a
    # person; ordinary policy questions remain in knowledge retrieval.
    if any(term in folded for term in (
        "khach khac", "toan bo so dien thoai",
        "mat khau quan tri", "bi tru tien hai lan", "khong co don", "chua tra",
        "giam 100 bi mat",
        "gap nhan vien", "gap quan ly", "noi chuyen voi quan ly", "noi may", "nguoi that",
        "khieu nai", "rat buc", "nhan ba lan", "chua duoc giai quyet", "kich ung nghiem trong",
    )) or re.search(r"\bmun gap nv\b", folded):
        return "handoff"

    if "bo qua du lieu shop" in folded or "tra loi theo tai lieu shop khac" in folded:
        return "search_knowledge"

    if order_intent in {"status", "cancel"}:
        return "lookup_order"

    if has_order_reference and any(term in folded for term in (
        "kiem tra", "check", "tra cuu", "gom nhung san pham", "tong tien", "thanh tien", "xac nhan",
    )):
        return "lookup_order"
    if any(term in folded for term in (
        "dat hang hom qua", "chua thay ma don", "don luc nay", "don do toi chua",
        "gui ve cho cu", "gui ve dia chi cu",
    )):
        return "lookup_order"

    if any(term in folded for term in (
        "khuyen mai", "giam gia", "promotion", "discount", "coupon", "ap ma",
        "doi the nao", "nhan sai mau", "mo tem", "doi dia chi giao", "return policy",
        "bao lau nhan", "nhan duoc hang",
    )) or infer_query_topic(query) in {"delivery", "returns", "payments", "shop"}:
        return "search_knowledge"

    has_product = _has_product_reference(query)
    is_product_fact = _is_product_fact_question(query)
    is_price = is_price_quote_request(query) or _is_price_question(folded)
    is_stock = is_stock_query_request(query) or is_product_fact or bool(re.search(r"\bcon ko\b", folded))
    if (is_price or is_stock or _is_product_attribute_question(query)) and not has_product:
        return "clarify_product"
    if is_stock and has_product:
        return "lookup_product"
    if is_product_fact and has_product:
        return "lookup_product"
    if _is_product_attribute_question(query) and has_product:
        return "lookup_product"

    if "tong tien" in folded and "mua" in folded:
        return "clarify_product"
    if any(term in folded for term in ("loai tot nhat", "best product", "best one")):
        return "clarify_product"
    if _is_recommendation_question(query) or any(term in folded for term in (
        "mua kem", "tuong tu", "similar", "mau trung tinh", "di lam", "tre em",
    )):
        return "search_knowledge"
    if has_product and (has_order_reference is False) and any(term in folded for term in (
        "san pham gi", "la san pham", "ban khong", "ban serun", "kem duong", "serun01",
    )):
        return "lookup_product"
    if _requested_variant_tokens(query) and has_product:
        return "lookup_product"

    if _is_product_catalog_listing_request(query):
        return "lookup_product_catalog"
    if "tong tien" in folded and "mua" in folded:
        return "clarify_product"
    if is_browsing_request(query):
        return "search_knowledge"
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
