"""Current tenant evidence shared by conversational advice and recommendations."""
import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy import or_
from app.models import Customer, CustomerFact
from app.services.customer_fact_extractor import has_customer_personalization_consent, get_customer_fact_extraction_enabled


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
    from app.services.recommendation_service import serve_recommendations, active_recommendation_experiment_id
    request = serve_recommendations(db, business_id=business_id, payload=RecommendationRequestCreate(
        customer_id=conversation.customer_id, query=query[:1000], limit=5,
        experiment_id=active_recommendation_experiment_id(db, business_id=business_id),
        context={"surface": "conversation_graph", "conversation_id": conversation.id},
    ))
    request.context = {**(request.context or {}), "surface":"conversation_graph", "conversation_id":conversation.id}
    db.flush()
    return {"request_id": request.request_id, "strategy": request.strategy,
        "model_version": request.model_version, "items": request.served_items or [],
        "personalization_applied": bool((request.context or {}).get("personalization_applied"))}


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
