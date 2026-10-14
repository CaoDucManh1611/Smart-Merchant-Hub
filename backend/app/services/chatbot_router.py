"""Shared deterministic commerce intent routing for serving and evaluation."""
import re

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


def classify_crm_query(query: str) -> str | None:
    """Route private CRM questions to tenant-scoped SQL, never to public RAG."""
    folded = fold_topic_text(query)
    has_customer = any(term in folded for term in (
        "khach", "customer", "ho so", "ma khach", "customer id",
    ))
    history_terms = (
        "lich su trao doi", "noi dung trao doi", "da noi gi voi", "conversation history",
        "message history", "chat history", "recent messages", "last conversation", "tin nhan gan day",
        "lich su tin nhan", "noi dung cuoc tro chuyen",
    )
    has_history = any(term in folded for term in history_terms)
    if has_history:
        if any(term in folded for term in ("ghi chu", "notes", "note noi bo")):
            return "lookup_crm_notes"
        return "lookup_crm_history"

    if any(term in folded for term in ("deal", "lead", "co hoi", "pipeline", "khach tiem nang")):
        return "lookup_crm_pipeline"

    customer_id_query = bool(re.search(
        r"(?:khach(?:\s+hang)?|customer|id|ma khach(?:\s+hang)?)\s*#?\s*\d+|#\d+",
        folded,
    ))
    customer_lookup_terms = (
        "tim khach", "tra cuu khach", "xem ho so", "ho so khach", "thong tin khach",
        "customer profile", "find customer", "lookup customer", "customer id",
        "ma khach", "id khach", "khach hang #", "ten khach", "khach ten",
    )
    if customer_id_query or (has_customer and any(term in folded for term in customer_lookup_terms)):
        if any(term in folded for term in ("ghi chu", "notes", "note noi bo")):
            return "lookup_crm_notes"
        return "lookup_crm_customer"
    if any(term in folded for term in ("ghi chu", "notes", "note noi bo")):
        return "lookup_crm_notes"
    return None


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


def classify_intent(query: str) -> str:
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

    current_month = any(term in folded for term in ("thang nay", "this month", "current month"))
    if current_month and any(term in folded for term in (
        "ban chay", "ban nhieu", "bestseller", "top san pham", "best selling", "top selling", "most sold",
        "doanh thu", "tong doanh so", "tong doanh thu", "sales revenue", "revenue",
    )):
        return "lookup_sales"

    if has_order_reference and any(term in folded for term in (
        "kiem tra", "check", "tra cuu", "gom nhung san pham", "tong tien", "thanh tien", "xac nhan",
        "toi dau", "den dau", "o dau", "where is", "where's", "order status", "tracking",
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



