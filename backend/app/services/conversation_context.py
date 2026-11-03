"""Current tenant evidence shared by conversational advice and recommendations."""
import hashlib
import json
import re
from datetime import datetime, timezone
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from app.models import Customer, CustomerFact
from app.services.customer_fact_extractor import has_customer_personalization_consent, get_customer_fact_extraction_enabled


_COMPATIBILITY_ATTRIBUTE_KEYS = (
    "compatible_model", "compatible_models", "compatible_with", "compatibility",
    "vehicle_compatibility", "vehicle_model", "fitment", "suitable_for",
)
_COMPATIBILITY_GENERIC_TOKENS = {
    "can", "cho", "danh", "dung", "doi", "hang", "khi", "loai", "may",
    "phu", "theo", "thi", "voi", "xe", "yeu", "cau", "honda", "yamaha",
    "chieu", "cu", "phai", "kiem", "tra", "va",
    "compatible", "fitment", "for", "model", "suitable", "use", "vehicle",
}


def _infer_compatibility_skus(db, business_id, query):
    """Find explicit catalog compatibility entities mentioned in a query.

    Catalog compatibility text often contains a longer instruction such as
    "Honda Wave Alpha 110 needs the old part checked". Match distinctive
    contiguous phrases against the current query, then pass the resulting SKU
    set to retrieval as an exact pre-LIMIT filter.
    """
    from app.models.recommendation_catalog import (
        RecommendationCatalogAttribute,
        RecommendationCatalogEntry,
    )
    from app.rag.topics import fold_topic_text

    folded_query = fold_topic_text(query)
    if not folded_query:
        return []
    padded_query = f" {folded_query} "

    try:
        with db.begin_nested():
            rows = db.query(
                RecommendationCatalogEntry.sku_norm,
                RecommendationCatalogAttribute.normalized_value,
            ).join(
                RecommendationCatalogAttribute,
                RecommendationCatalogAttribute.catalog_entry_id == RecommendationCatalogEntry.id,
            ).filter(
                RecommendationCatalogEntry.business_id == business_id,
                RecommendationCatalogEntry.object_type == "product",
                RecommendationCatalogEntry.status == "active",
                RecommendationCatalogEntry.sku_norm.is_not(None),
                RecommendationCatalogAttribute.key_norm.in_(_COMPATIBILITY_ATTRIBUTE_KEYS),
            ).all()
    except SQLAlchemyError:
        # A shop awaiting the catalog migration keeps its existing retrieval path.
        return []
    if not rows:
        return []

    # An exact SKU query already has its own stronger parser in retrieve().
    for sku, _value in rows:
        sku_phrase = fold_topic_text(sku)
        if sku_phrase and f" {sku_phrase} " in padded_query:
            return []

    phrase_skus = {}
    for sku, value in rows:
        normalized = fold_topic_text(value)
        tokens = re.findall(r"[a-z0-9]+", normalized)
        for size in range(2, min(5, len(tokens)) + 1):
            for start in range(len(tokens) - size + 1):
                phrase_tokens = tokens[start:start + size]
                informative = [
                    token for token in phrase_tokens
                    if token not in _COMPATIBILITY_GENERIC_TOKENS
                ]
                # Ignore generic phrases like "xe so" while allowing model
                # names and numeric variants such as "Vision 110".
                if not informative or not any(len(token) >= 4 or any(ch.isdigit() for ch in token) for token in informative):
                    continue
                phrase = " ".join(phrase_tokens)
                if f" {phrase} " in padded_query:
                    phrase_skus.setdefault(phrase, set()).add(str(sku).strip().casefold())

    if not phrase_skus:
        return []
    # Multiple explicit entities (for example a comparison) remain a union.
    matched_skus = set().union(*phrase_skus.values())
    all_compatibility_skus = {str(sku).strip().casefold() for sku, _value in rows if sku}
    if (
        not matched_skus
        or len(matched_skus) > 10
        or matched_skus == all_compatibility_skus
    ):
        return []
    return sorted(matched_skus)


def customer_memory(db, business_id, customer_id):
    customer = db.query(Customer).filter(Customer.business_id == business_id, Customer.id == customer_id, Customer.status != "merged").first()
    if customer is None:
        return {"personalization_allowed": False, "facts": []}
    allowed = (not customer.fact_extraction_opt_out
        and get_customer_fact_extraction_enabled(db, business_id)
        and has_customer_personalization_consent(db, business_id=business_id, customer_id=customer_id))
    result = {"name": customer.name, "personalization_allowed": bool(allowed), "facts": []}
    if not allowed:
        return result
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    facts = db.query(CustomerFact).filter(
        CustomerFact.business_id == business_id, CustomerFact.customer_id == customer_id,
        or_(CustomerFact.valid_from.is_(None), CustomerFact.valid_from <= now),
        or_(CustomerFact.valid_until.is_(None), CustomerFact.valid_until > now),
        or_(CustomerFact.is_verified.is_(True), CustomerFact.confidence >= 0.85),
    ).order_by(CustomerFact.is_verified.desc(), CustomerFact.updated_at.desc(), CustomerFact.id.desc()).all()
    seen = set()
    for fact in facts:
        key = (fact.fact_type, fact.fact_key)
        if key in seen:
            continue
        seen.add(key)
        result["facts"].append({"id": fact.id, "type": fact.fact_type, "key": fact.fact_key,
            "value": fact.fact_value_json, "verified": fact.is_verified, "confidence": fact.confidence,
            "source_type": fact.source_type, "source_message_id": fact.source_message_id,
            "source_order_id": fact.source_order_id, "updated_at": str(fact.updated_at)})
        if len(result["facts"]) == 20:
            break
    return result


def recommendation_evidence(db, business_id, conversation, query):
    from app.schemas.recommendation import RecommendationRequestCreate
    from app.rag.retriever import retrieve
    from app.rag.catalog_filters import extract_query_hard_filters
    from app.services.recommendation_service import (
        active_recommendation_experiment_id,
        rag_candidates_from_chunks,
        serve_recommendations,
    )
    retrieval_diagnostics = {}
    hard_filters = extract_query_hard_filters(query, object_type="product")
    compatibility_skus = _infer_compatibility_skus(db, business_id, query)
    if compatibility_skus and not hard_filters.get("sku"):
        hard_filters["sku"] = compatibility_skus
        retrieval_diagnostics["catalog_compatibility_filter"] = "exact_sku_set"
        retrieval_diagnostics["catalog_compatibility_sku_count"] = len(compatibility_skus)
    chunks = retrieve(
        query=query,
        db=db,
        business_id=business_id,
        top_k=30,
        diagnostics=retrieval_diagnostics,
        hard_filters=hard_filters,
    )
    rag_candidates, retrieval_trace = rag_candidates_from_chunks(
        db, business_id=business_id, chunks=chunks,
    )
    request = serve_recommendations(db, business_id=business_id, payload=RecommendationRequestCreate(
        customer_id=conversation.customer_id, query=query[:1000], limit=5,
        experiment_id=active_recommendation_experiment_id(db, business_id=business_id),
        rag_candidates=rag_candidates,
        context={
            "surface": "conversation_graph",
            "conversation_id": conversation.id,
            "source_channel": str(conversation.channel or "unknown"),
            "retrieval_trace": retrieval_trace,
            "retrieval_diagnostics": retrieval_diagnostics,
            "hard_filters": hard_filters,
        },
    ), record_impressions=False)
    request_context = request.context or {}
    rfm_ranking = {
        "applied": bool(request_context.get("rfm_model_applied")),
        "weighting_applied": bool(request_context.get("rfm_ranker_applied")),
        "blend_version": request_context.get("rfm_ranker_version"),
        "model_version": request_context.get("rfm_model_version"),
        "source": request_context.get("rfm_model_source"),
        "industry": request_context.get("rfm_model_industry"),
        "segment": request_context.get("rfm_segment"),
    }
    request.context = {**request_context, "surface":"conversation_graph", "conversation_id":conversation.id}
    db.flush()
    return {"request_id": request.request_id, "strategy": request.strategy,
        "model_version": request.model_version, "items": request.served_items or [],
        "personalization_applied": bool(request_context.get("personalization_applied")),
        "rfm_ranking": rfm_ranking}


def evidence_manifest(evidence):
    # Hashes expose provenance changes without copying customer facts into logs.
    return [{"source": item.split(":", 1)[0].split(" — ", 1)[0][:80],
        "sha256": hashlib.sha256(item.encode()).hexdigest()} for item in evidence]


def approved_reply_style(db, business_id, conversation, query, job_key):
    from app.services.chatbot_bandit_service import select_chatbot_reply_choice
    from app.rag.topics import infer_query_topic
    if not customer_memory(db,business_id,conversation.customer_id)["personalization_allowed"]:
        return None
    return select_chatbot_reply_choice(db,business_id=business_id,conversation_id=conversation.id,
        channel=conversation.channel,query_topic=infer_query_topic(query),auto_reply_key=f"graph:{job_key}")
