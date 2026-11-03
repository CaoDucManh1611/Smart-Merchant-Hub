"""Structured, deterministic intent decisions for shop customer messages.

This layer describes the route selected by the existing business rules; it does
not introduce another model call or replace the handlers that own each action.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from app.rag.topics import fold_topic_text
from app.rag.lexical import identifiers


@dataclass(frozen=True)
class IntentDecision:
    intent: str
    industry: str | None
    entities: dict[str, Any]
    needs_catalog: bool
    needs_docs: bool
    # Heuristic telemetry only. This is not a calibrated probability and does
    # not trigger an extra model call or alter the handler selected below.
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _entities(query: str) -> dict[str, Any]:
    folded = fold_topic_text(query)
    sku = re.search(
        r"\b(?:sku|mã(?:\s+(?:sản phẩm|hàng))?|ma(?:\s+(?:san pham|hang))?|model)\s*[:#]?\s*([a-z0-9]+(?:[-_][a-z0-9]+)+)\b",
        query, re.IGNORECASE,
    )
    sku_value = sku.group(1).upper() if sku else next((
        value.upper() for value in identifiers(query)
        if value.count("-") + value.count("_") >= 2
    ), None)
    budget = re.search(r"(?:duoi|toi da|ngan sach|under|below|budget)\s*([\d.,]+)\s*(trieu|tr|nghin|ngan|k)?", folded)
    size = re.search(r"\b(?:size|co)\s*(xxs|xs|s|m|l|xl|xxl|xxxl)\b", folded)
    color = re.search(r"\b(?:mau|color|colour)\s+(den|trang|do|xanh|hong|vang|black|white|red|blue|pink|yellow)\b", folded)
    result: dict[str, Any] = {}
    if sku_value:
        result["sku"] = sku_value
    if budget:
        result["budget_text"] = " ".join(part for part in budget.groups() if part)
    if size:
        result["size"] = size.group(1).upper()
    if color:
        result["color"] = color.group(1)
    return result


def build_intent_decision(
    query: str,
    intent: str,
    *,
    industry: str | None = None,
    catalog_required: bool = False,
) -> IntentDecision:
    """Map the stable legacy route to one inspectable decision record."""
    entities = _entities(query)
    catalog_intents = {"lookup_product", "lookup_product_catalog", "clarify_product"}
    docs_intents = {"search_knowledge"}
    needs_catalog = intent in catalog_intents or bool(entities.get("sku")) or catalog_required
    folded = fold_topic_text(query)
    docs_cues = (
        "chinh sach", "bao hanh", "doi tra", "huong dan", "thanh phan", "cach dung",
        "mo ta", "chi tiet", "tuong thich", "giai thich", "so sanh", "phu hop",
        "policy", "warranty", "return", "ingredients", "how to use", "description",
        "details", "compatible", "compare", "recommend", "recommendation",
    )
    needs_docs = (
        intent in docs_intents
        or intent == "clarify_product"
        or any(cue in folded for cue in docs_cues)
    )
    if intent == "search_knowledge" and not folded:
        confidence, reason = 0.0, "empty_query"
    elif intent == "search_knowledge" and not any(("?" in query, len(folded.split()) >= 2)):
        confidence, reason = 0.55, "generic_knowledge_fallback"
    elif intent == "search_knowledge":
        confidence, reason = 0.62, "safe_knowledge_fallback_rule"
    else:
        confidence, reason = 0.9, "specific_rule_match"
    return IntentDecision(
        intent=intent,
        industry=(industry.strip().casefold() if isinstance(industry, str) and industry.strip() else None),
        entities=entities,
        needs_catalog=needs_catalog,
        needs_docs=needs_docs,
        confidence=confidence,
        reason=reason,
    )


def route_customer_message(
    query: str,
    *,
    industry: str | None = None,
    catalog_required: bool = False,
) -> IntentDecision:
    """Return one inspectable decision using the existing deterministic router.

    The current action rules remain the source of truth; this wrapper gives
    callers a single structured result without adding another model request.
    """
    from app.services.chatbot_router import classify_intent

    action = classify_intent(query)
    return build_intent_decision(
        query,
        action,
        industry=industry,
        catalog_required=catalog_required,
    )
