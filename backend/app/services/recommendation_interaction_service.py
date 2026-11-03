"""Tenant-safe behavioral event ingestion for product recommendations."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unicodedata
from typing import Any

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.customer_collection import CustomerConsent
from app.models.conversation import Conversation
from app.models.experimentation import BanditArmStat, BanditDecision
from app.models.message import Message
from app.models.recommendation import (
    CustomerProductInteraction,
    RecommendationFeedback,
    RecommendationRequest,
)
from app.models.recommendation_catalog import RecommendationCatalogEntry
from app.models.sales import Order, OrderItem, Product
from app.services.recommendation_learning import LIGHTFM_ALGORITHM, LIVE_RERANKER_ALGORITHM


PRODUCT_REQUIRED_EVENTS = {"view", "impression", "click", "cart", "checkout_intent", "purchase", "skip", "refund"}
_PERSONALIZED_FEATURE_KEYS = (
    "affinity_score", "co_purchase_score", "interaction_score", "purchase_facet_score",
    "historic_query_overlap_score", "purchase_facet_affinity", "stated_preference_score",
    "color_match", "ncf_score", "linucb_score", "rfm_segment",
)


def _behavioral_reranker_log(context: dict[str, Any]) -> dict[str, Any]:
    trace = context.get("behavioral_reranker")
    if not isinstance(trace, dict) or trace.get("algorithm") not in {LIVE_RERANKER_ALGORITHM, LIGHTFM_ALGORITHM}:
        return {}
    return {
        key: trace.get(key)
        for key in (
            "algorithm", "blend_version", "applied", "query_intent", "retrieval_weight",
            "model_weight", "training_run_id", "candidate_pool_size", "scored_candidate_count",
        )
    }


class RecommendationInteractionError(ValueError):
    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


_FEEDBACK_REWARDS = {
    "impression": Decimal("0"),
    "click": Decimal("0.2"),
    "cart": Decimal("0.5"),
    "checkout_intent": Decimal("0.2"),
    "purchase": Decimal("1"),
    "skip": Decimal("-0.35"),
    "refund": Decimal("-1"),
}


def apply_recommendation_outcome(
    db: Session,
    *,
    request: RecommendationRequest,
    product_id: int,
    event_type: str,
    idempotency_key: str,
    metadata: dict[str, Any] | None = None,
) -> RecommendationFeedback:
    """Persist a recommendation outcome and update its bandit reward once."""
    existing = db.query(RecommendationFeedback).filter(
        RecommendationFeedback.business_id == request.business_id,
        RecommendationFeedback.idempotency_key == idempotency_key,
    ).first()
    if existing is not None:
        return existing
    reward = _FEEDBACK_REWARDS[event_type]
    event_metadata = {
        **(metadata or {}),
        **_recommendation_event_snapshot(db, request=request, product_id=product_id),
    }
    feedback = RecommendationFeedback(
        business_id=request.business_id,
        recommendation_request_id=request.id,
        product_id=product_id,
        event_type=event_type,
        reward=reward,
        idempotency_key=idempotency_key,
        event_metadata=event_metadata,
    )
    db.add(feedback)

    if event_type in {"purchase", "skip", "refund"} and request.bandit_decision_id is not None:
        decision = db.get(BanditDecision, request.bandit_decision_id)
        if decision is not None:
            previous = Decimal(str(decision.reward)) if decision.reward is not None else None
            # A later full refund reverses the earlier purchase reward without
            # adding a second training example. Other terminal outcomes are first-write-wins.
            replace_previous = (
                (event_type == "refund" and previous != reward)
                or (event_type == "purchase" and previous is not None and previous <= 0)
            )
            if previous is None or replace_previous:
                decision.reward = reward
                decision.reward_idempotency_key = idempotency_key
                if decision.policy_id is not None and decision.context_hash:
                    stat = db.query(BanditArmStat).filter(
                        BanditArmStat.business_id == request.business_id,
                        BanditArmStat.policy_id == decision.policy_id,
                        BanditArmStat.arm == decision.arm,
                        BanditArmStat.context_hash == decision.context_hash,
                    ).first()
                    if stat is None:
                        stat = BanditArmStat(
                            business_id=request.business_id,
                            policy_id=decision.policy_id,
                            arm=decision.arm,
                            context_hash=decision.context_hash,
                            pulls=0,
                            reward_sum=Decimal("0"),
                        )
                        db.add(stat)
                    if previous is None:
                        stat.pulls = int(stat.pulls or 0) + 1
                    stat.reward_sum = Decimal(stat.reward_sum or 0) + reward - (previous or Decimal("0"))
    db.flush()
    return feedback


def _occurred_at(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _existing_or_add(
    db: Session,
    *,
    business_id: int,
    idempotency_key: str,
    values: dict[str, Any],
) -> CustomerProductInteraction:
    existing = db.query(CustomerProductInteraction).filter(
        CustomerProductInteraction.business_id == business_id,
        CustomerProductInteraction.idempotency_key == idempotency_key,
    ).first()
    if existing is not None:
        return existing
    row = CustomerProductInteraction(
        business_id=business_id,
        idempotency_key=idempotency_key,
        **values,
    )
    db.add(row)
    db.flush()
    return row


def _has_personalization_consent(db: Session, *, business_id: int, customer_id: int | None) -> bool:
    if customer_id is None:
        return False
    consent = db.query(CustomerConsent.status).filter(
        CustomerConsent.business_id == business_id,
        CustomerConsent.customer_id == customer_id,
        CustomerConsent.purpose == "personalization",
    ).order_by(CustomerConsent.id.desc()).first()
    return consent is not None and consent[0] == "granted"


def _recommendation_event_snapshot(
    db: Session,
    *,
    request: RecommendationRequest,
    product_id: int | None = None,
    object_type: str = "product",
    recommendation_object_id: str | None = None,
) -> dict[str, Any]:
    """Copy server-owned ranking features onto each linked outcome event."""
    context = request.context if isinstance(request.context, dict) else {}
    served_item = None
    position = None
    target_id = str(recommendation_object_id if recommendation_object_id is not None else product_id)
    for item_position, item in enumerate(request.served_items or [], start=1):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("object_type") or "product").casefold()
        item_id = item.get("recommendation_object_id")
        if item_id is None:
            item_id = item.get("product_id") if item_type == "product" else item.get("object_id")
        matches = item_type == object_type and str(item_id) == target_id
        if matches:
            served_item = item
            position = int(item.get("position") or item_position)
            break
    served_item = served_item if isinstance(served_item, dict) else {}
    consent_granted = _has_personalization_consent(
        db, business_id=request.business_id, customer_id=request.customer_id,
    )
    feature_snapshot = dict(served_item.get("feature_snapshot")) if isinstance(served_item.get("feature_snapshot"), dict) else {}
    if not consent_granted:
        for key in _PERSONALIZED_FEATURE_KEYS:
            feature_snapshot.pop(key, None)
    reranker_log = _behavioral_reranker_log(context)
    snapshot: dict[str, Any] = {
        "request_id": request.request_id,
        "strategy": request.strategy,
        "model_version": request.model_version,
        "object_type": object_type,
        "recommendation_object_id": target_id,
        "catalog_revision": served_item.get("catalog_revision"),
        "position": position,
        "score": served_item.get("score"),
        "feature_snapshot": feature_snapshot,
        "query_hash": context.get("query_hash"),
        "query_chars": context.get("query_chars"),
        "surface": context.get("surface"),
        "item_selection_policy": context.get("item_selection_policy"),
        "item_policy_randomized": bool(context.get("item_policy_randomized", False)),
        "strategy_selection": context.get("strategy_selection") if isinstance(context.get("strategy_selection"), dict) else {},
        "blend_version": context.get("blend_version") or reranker_log.get("blend_version"),
        "behavioral_reranker": reranker_log,
    }
    if consent_granted:
        snapshot.update({
            "rfm_segment": context.get("rfm_segment"),
            "rfm_rules_version": context.get("rfm_rules_version"),
            "rfm_snapshot": context.get("rfm_snapshot") if isinstance(context.get("rfm_snapshot"), dict) else None,
        })
    return snapshot


def record_interaction(
    db: Session,
    *,
    business_id: int,
    customer_id: int | None,
    product_id: int | None,
    object_type: str = "product",
    recommendation_object_id: str | None = None,
    request_id: str | None,
    event_type: str,
    source: str,
    query: str | None,
    idempotency_key: str,
    metadata: dict[str, Any] | None,
    occurred_at: datetime | None,
) -> tuple[CustomerProductInteraction, str | None]:
    """Validate tenant ownership, then persist an idempotent user signal."""
    normalized_event = event_type.strip().lower()
    normalized_source = source.strip().lower()
    normalized_object_type = str(object_type or "product").strip().casefold()
    if normalized_object_type not in {"product", "service", "rental"}:
        raise RecommendationInteractionError("object_type không hợp lệ.")
    if normalized_object_type != "product" and product_id is not None:
        raise RecommendationInteractionError("product_id chỉ dùng cho object_type=product.")
    if normalized_object_type == "product" and product_id is None and recommendation_object_id and str(recommendation_object_id).isdigit():
        product_id = int(recommendation_object_id)
    if product_id is not None and recommendation_object_id is not None and str(product_id) != str(recommendation_object_id):
        raise RecommendationInteractionError("product_id và recommendation_object_id không khớp.")
    object_id = str(recommendation_object_id or product_id or "").strip() or None
    if normalized_event in PRODUCT_REQUIRED_EVENTS and object_id is None:
        raise RecommendationInteractionError("Loại interaction này cần ID đối tượng được gợi ý.")
    if customer_id is not None:
        customer = db.query(Customer).filter(
            Customer.id == customer_id,
            Customer.business_id == business_id,
            Customer.status != "merged",
        ).first()
        if customer is None:
            raise RecommendationInteractionError("Khách hàng không tồn tại trong shop này.", 404)
        latest_consent = db.query(CustomerConsent).filter(
            CustomerConsent.business_id == business_id,
            CustomerConsent.customer_id == customer_id,
            CustomerConsent.purpose == "personalization",
        ).order_by(CustomerConsent.id.desc()).first()
        if latest_consent is None or latest_consent.status != "granted":
            customer_id = None
            query = None
            metadata = None
    if product_id is not None:
        product = db.query(Product).filter(
            Product.id == product_id,
            Product.business_id == business_id,
        ).first()
        if product is None:
            raise RecommendationInteractionError("Sản phẩm không tồn tại trong shop này.", 404)
    elif object_id is not None:
        catalog_entry = db.query(RecommendationCatalogEntry).filter(
            RecommendationCatalogEntry.business_id == business_id,
            RecommendationCatalogEntry.object_type == normalized_object_type,
            RecommendationCatalogEntry.external_id == object_id,
        ).first()
        if catalog_entry is None:
            raise RecommendationInteractionError("Đối tượng gợi ý không tồn tại trong shop này.", 404)

    request: RecommendationRequest | None = None
    if request_id:
        request = db.query(RecommendationRequest).filter(
            RecommendationRequest.business_id == business_id,
            RecommendationRequest.request_id == request_id,
        ).first()
        if request is None:
            raise RecommendationInteractionError("Lần gợi ý không tồn tại trong shop này.", 404)
        if customer_id is not None and request.customer_id is not None and request.customer_id != customer_id:
            raise RecommendationInteractionError("Customer không khớp với lần gợi ý.", 409)
        if normalized_event in PRODUCT_REQUIRED_EVENTS and object_id is not None:
            served_ids = set()
            for item in request.served_items or []:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("object_type") or "product").casefold()
                item_id = item.get("recommendation_object_id")
                if item_id is None:
                    item_id = item.get("product_id") if item_type == "product" else item.get("object_id")
                if item_id is not None:
                    served_ids.add((item_type, str(item_id)))
            if (normalized_object_type, object_id) not in served_ids:
                raise RecommendationInteractionError("Đối tượng không thuộc danh sách đã gợi ý.", 409)
            metadata = {
                **(metadata or {}),
                **_recommendation_event_snapshot(
                    db, request=request, product_id=product_id,
                    object_type=normalized_object_type, recommendation_object_id=object_id,
                ),
            }

    row = _existing_or_add(
        db,
        business_id=business_id,
        idempotency_key=idempotency_key.strip(),
        values={
            "customer_id": customer_id,
            "product_id": product_id,
            "object_type": normalized_object_type,
            "recommendation_object_id": object_id,
            "catalog_revision": (
                int(metadata["catalog_revision"])
                if isinstance(metadata, dict) and str(metadata.get("catalog_revision", "")).isdigit()
                else None
            ),
            "model_version": (
                str(metadata["model_version"])[:120]
                if isinstance(metadata, dict) and metadata.get("model_version")
                else (request.model_version if request else None)
            ),
            "recommendation_request_id": request.id if request else None,
            "event_type": normalized_event,
            "source": normalized_source,
            "query_text": (query or "").strip() or None,
            "event_metadata": metadata or {},
            "occurred_at": _occurred_at(occurred_at),
        },
    )
    return row, request.request_id if request else None


def record_recommendation_impressions(
    db: Session,
    *,
    request: RecommendationRequest,
    source: str = "recommendation",
    conversation_id: int | None = None,
    message_id: int | None = None,
    channel: str | None = None,
    product_ids: set[int] | None = None,
    object_refs: set[tuple[str, str]] | None = None,
) -> None:
    """Record each displayed item once, with its ranker snapshot."""
    context = request.context if isinstance(request.context, dict) else {}
    consent_granted = _has_personalization_consent(
        db, business_id=request.business_id, customer_id=request.customer_id,
    )
    reranker_log = _behavioral_reranker_log(context)
    for position, item in enumerate(request.served_items or [], start=1):
        if not isinstance(item, dict):
            continue
        object_type = str(item.get("object_type") or "product").casefold()
        object_id = item.get("recommendation_object_id")
        if object_id is None:
            object_id = item.get("product_id") if object_type == "product" else item.get("object_id")
        if object_type not in {"product", "service", "rental"} or object_id is None:
            continue
        object_id = str(object_id)
        product_id = int(object_id) if object_type == "product" and object_id.isdigit() else None
        if object_type == "product" and product_id is None:
            continue
        if product_ids is not None and (product_id is None or product_id not in product_ids):
            continue
        if object_refs is not None and (object_type, object_id) not in object_refs:
            continue
        feature_snapshot = dict(item.get("feature_snapshot")) if isinstance(item.get("feature_snapshot"), dict) else {}
        if not consent_granted:
            for key in _PERSONALIZED_FEATURE_KEYS:
                feature_snapshot.pop(key, None)
        _existing_or_add(
            db,
            business_id=request.business_id,
            idempotency_key=f"recommendation:{request.request_id}:impression:{object_type}:{object_id}",
            values={
                "customer_id": request.customer_id if consent_granted else None,
                "product_id": product_id,
                "object_type": object_type,
                "recommendation_object_id": object_id,
                "catalog_revision": int(item["catalog_revision"]) if str(item.get("catalog_revision", "")).isdigit() else None,
                "model_version": request.model_version,
                "recommendation_request_id": request.id,
                "event_type": "impression",
                "source": source,
                "query_text": None,
                "event_metadata": {
                    "request_id": request.request_id,
                    "object_type": object_type,
                    "recommendation_object_id": object_id,
                    "catalog_revision": int(item["catalog_revision"]) if str(item.get("catalog_revision", "")).isdigit() else None,
                    "strategy": request.strategy,
                    "model_version": request.model_version,
                    "blend_version": context.get("blend_version") or reranker_log.get("blend_version"),
                    "behavioral_reranker": reranker_log,
                    "position": int(item.get("position") or position),
                    "selection_probability": item.get("selection_probability"),
                    "score": item.get("score"),
                    "quality_validation": item.get("quality_validation") if isinstance(item.get("quality_validation"), dict) else None,
                    "feature_snapshot": feature_snapshot,
                    "surface": context.get("surface"),
                    "conversation_id": conversation_id or context.get("conversation_id"),
                    "message_id": message_id,
                    "channel": channel or context.get("source_channel"),
                    "item_selection_policy": context.get("item_selection_policy", "deterministic_ranker"),
                    "item_policy_randomized": bool(context.get("item_policy_randomized", False)),
                    "strategy_selection": context.get("strategy_selection") if isinstance(context.get("strategy_selection"), dict) else {},
                    "query_hash": context.get("query_hash"),
                    "query_chars": context.get("query_chars"),
                    "rfm_segment": context.get("rfm_segment") if consent_granted else None,
                    "rfm_rules_version": context.get("rfm_rules_version") if consent_granted else None,
                    "rfm_snapshot": context.get("rfm_snapshot") if consent_granted and isinstance(context.get("rfm_snapshot"), dict) else None,
                    "retrieval_diagnostics": context.get("retrieval_diagnostics") if isinstance(context.get("retrieval_diagnostics"), dict) else {},
                },
                "occurred_at": _occurred_at(None),
            },
        )


def record_chat_recommendation_impressions(
    db: Session,
    *,
    business_id: int,
    conversation_id: int,
    message_id: int | None,
    channel: str,
    recommendation: dict[str, Any] | None,
) -> bool:
    """Record recommendations only after their outbound chat message was saved."""
    request_id = recommendation.get("request_id") if isinstance(recommendation, dict) else None
    if not request_id:
        return False
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == business_id,
    ).first()
    if conversation is None:
        return False
    message = db.query(Message).filter(
        Message.id == message_id,
        Message.conversation_id == conversation_id,
        Message.sender_type == "bot",
        Message.direction == "outbound",
        Message.status == "sent",
    ).first() if message_id is not None else None
    if message is None:
        return False
    message_metadata = message.metadata_ if isinstance(message.metadata_, dict) else {}
    saved_recommendation = message_metadata.get("recommendation")
    if not isinstance(saved_recommendation, dict) or str(saved_recommendation.get("request_id")) != str(request_id):
        return False
    request = db.query(RecommendationRequest).filter(
        RecommendationRequest.business_id == business_id,
        RecommendationRequest.request_id == str(request_id),
    ).first()
    if request is None:
        return False
    context = request.context if isinstance(request.context, dict) else {}
    if context.get("conversation_id") != conversation_id:
        return False
    if request.customer_id is not None and request.customer_id != conversation.customer_id:
        return False
    def fold_visible_text(value: str) -> str:
        folded = "".join(
            char for char in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(char)
        ).replace("đ", "d")
        return " ".join("".join(char if char.isalnum() or char.isspace() else " " for char in folded).split())

    visible_text = fold_visible_text(str(message.content or ""))
    padded_visible_text = f" {visible_text} "
    displayed_object_refs: set[tuple[str, str]] = set()
    for item in request.served_items or []:
        if not isinstance(item, dict):
            continue
        object_type = str(item.get("object_type") or "product").casefold()
        object_id = item.get("recommendation_object_id")
        if object_id is None:
            object_id = item.get("product_id") if object_type == "product" else item.get("object_id")
        if object_type not in {"product", "service", "rental"} or object_id is None:
            continue
        name = fold_visible_text(str(item.get("name") or ""))
        sku = fold_visible_text(str(item.get("sku") or ""))
        click_url = str(item.get("click_url") or "")
        name_visible = len(name) >= 3 and f" {name} " in padded_visible_text
        sku_visible = bool(sku) and f" {sku} " in padded_visible_text
        if name_visible or sku_visible or (click_url and click_url in str(message.content or "")):
            displayed_object_refs.add((object_type, str(object_id)))
    if not displayed_object_refs:
        return False
    record_recommendation_impressions(
        db,
        request=request,
        source="chatbot",
        conversation_id=conversation_id,
        message_id=message_id,
        channel=channel,
        object_refs=displayed_object_refs,
    )
    return True


def record_chat_recommendation_cart(
    db: Session,
    *,
    business_id: int,
    customer_id: int,
    conversation_id: int | None,
    collection_session_id: int,
    product_ids: set[int],
) -> int:
    """Link a confirmed quote/cart line to a recently displayed recommendation.

    Attribution requires a real chatbot impression for the same conversation
    and product; merely mentioning or browsing a catalog item is not enough.
    """
    if not conversation_id or not product_ids:
        return 0
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == business_id,
        Conversation.customer_id == customer_id,
    ).first()
    if conversation is None:
        return 0

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
    recorded = 0
    for product_id in sorted(product_ids):
        impressions = db.query(CustomerProductInteraction).join(
            RecommendationRequest,
            RecommendationRequest.id == CustomerProductInteraction.recommendation_request_id,
        ).filter(
            CustomerProductInteraction.business_id == business_id,
            CustomerProductInteraction.customer_id == customer_id,
            CustomerProductInteraction.product_id == product_id,
            CustomerProductInteraction.event_type == "impression",
            CustomerProductInteraction.source == "chatbot",
            CustomerProductInteraction.recommendation_request_id.is_not(None),
            CustomerProductInteraction.occurred_at >= cutoff,
            RecommendationRequest.business_id == business_id,
        ).order_by(CustomerProductInteraction.occurred_at.desc()).limit(30).all()

        request = None
        for impression in impressions:
            metadata = impression.event_metadata if isinstance(impression.event_metadata, dict) else {}
            try:
                same_conversation = int(metadata.get("conversation_id")) == conversation_id
            except (TypeError, ValueError):
                same_conversation = False
            if not same_conversation:
                continue
            candidate = db.get(RecommendationRequest, impression.recommendation_request_id)
            if candidate is None or candidate.business_id != business_id:
                continue
            if candidate.customer_id is not None and candidate.customer_id != customer_id:
                continue
            if not any(
                isinstance(item, dict) and str(item.get("product_id", "")).isdigit()
                and int(item["product_id"]) == product_id
                for item in (candidate.served_items or [])
            ):
                continue
            request = candidate
            break
        if request is None:
            continue

        idempotency_key = f"chat-cart:{collection_session_id}:{request.request_id}:{product_id}"
        record_interaction(
            db,
            business_id=business_id,
            customer_id=customer_id,
            product_id=product_id,
            request_id=request.request_id,
            event_type="checkout_intent",
            source="chat_checkout",
            query=None,
            idempotency_key=idempotency_key,
            metadata={
                "collection_session_id": collection_session_id,
                "cart_action": "order_confirmation_quote",
            },
            occurred_at=None,
        )
        apply_recommendation_outcome(
            db,
            request=request,
            product_id=product_id,
            event_type="checkout_intent",
            idempotency_key=f"{idempotency_key}:feedback",
            metadata={"source": "chat_checkout", "collection_session_id": collection_session_id},
        )
        recorded += 1
    return recorded


def _recommendation_request_for_order_item(
    db: Session, *, order: Order, item: OrderItem
) -> RecommendationRequest | None:
    """Attribute a sale only to a recommendation actually saved in this buyer's chat."""
    if order.customer_id is None:
        return None
    if order.conversation_id is not None:
        conversation_ids = [int(order.conversation_id)]
    else:
        conversation_ids = [int(value) for (value,) in db.query(Conversation.id).filter(
            Conversation.business_id == order.business_id,
            Conversation.customer_id == order.customer_id,
        ).all()]
    if not conversation_ids:
        return None

    cutoff = _occurred_at(order.created_at) - timedelta(days=30)
    messages = db.query(Message).join(
        Conversation, Conversation.id == Message.conversation_id,
    ).filter(
        Conversation.business_id == order.business_id,
        Conversation.customer_id == order.customer_id,
        Conversation.id.in_(conversation_ids),
        Message.direction == "outbound",
        Message.sender_type == "bot",
        Message.status.in_(("sent", "received")),
    ).order_by(Message.id.desc()).limit(200).all()
    request_ids: list[str] = []
    for message in messages:
        metadata = message.metadata_ if isinstance(message.metadata_, dict) else {}
        recommendation = metadata.get("recommendation")
        request_id = recommendation.get("request_id") if isinstance(recommendation, dict) else None
        if request_id and str(request_id) not in request_ids:
            request_ids.append(str(request_id))

    order_at = _occurred_at(order.created_at)
    for request_id in request_ids:
        request = db.query(RecommendationRequest).filter(
            RecommendationRequest.business_id == order.business_id,
            RecommendationRequest.request_id == request_id,
            RecommendationRequest.customer_id == order.customer_id,
        ).first()
        if request is None or request.created_at is None:
            continue
        requested_at = _occurred_at(request.created_at)
        if requested_at < cutoff or requested_at > order_at:
            continue
        if any(
            isinstance(served, dict)
            and str(served.get("product_id", "")).isdigit()
            and int(served["product_id"]) == int(item.product_id)
            for served in (request.served_items or [])
        ):
            return request
    return None


def record_explicit_chat_recommendation_decline(
    db: Session,
    *,
    business_id: int,
    conversation_id: int,
    text: str,
    source_message_id: int | None = None,
) -> bool:
    """Record a high-confidence refusal only when it directly follows a sent recommendation."""
    raw_text = str(text or "").strip()
    if "?" in raw_text or "？" in raw_text:
        return False
    folded = "".join(
        char for char in unicodedata.normalize("NFKD", raw_text.lower())
        if not unicodedata.combining(char)
    )
    folded = folded.replace("’", "'").replace("'", "")
    folded = " ".join("".join(char if char.isalnum() or char.isspace() else " " for char in folded).split())
    decline_phrases = (
        "khong thich", "khong hop", "khong phu hop", "khong lay", "khong can",
        "khong mua", "khong ung", "thoi khong", "bo qua", "not interested", "not a fit",
        "not for me", "do not want", "dont want", "dont like", "no thanks", "ill pass", "i will pass",
    )
    follow_up_markers = (
        "nhung", "co mau", "mau khac", "mau xanh", "doi sang", "tim mau", "goi y", "cho toi xem",
    )
    if (
        not any(phrase in folded for phrase in decline_phrases)
        or any(marker in folded for marker in follow_up_markers)
    ):
        return False

    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == business_id,
    ).first()
    if conversation is None or conversation.customer_id is None:
        return False
    customer = db.query(Customer).filter(
        Customer.id == conversation.customer_id,
        Customer.business_id == business_id,
        Customer.fact_extraction_opt_out.is_(False),
        Customer.status != "merged",
    ).first()
    if customer is None:
        return False
    consent = db.query(CustomerConsent.status).filter(
        CustomerConsent.business_id == business_id,
        CustomerConsent.customer_id == conversation.customer_id,
        CustomerConsent.purpose == "personalization",
    ).order_by(CustomerConsent.id.desc()).first()
    if consent is None or consent[0] != "granted":
        return False

    latest_inbound_id = db.query(Message.id).filter(
        Message.conversation_id == conversation_id,
        Message.direction == "inbound",
    ).order_by(Message.id.desc()).limit(1).scalar()
    if latest_inbound_id is None:
        return False
    if source_message_id is not None and int(latest_inbound_id) != int(source_message_id):
        return False
    candidates = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.direction == "outbound",
        Message.sender_type == "bot",
        Message.status == "sent",
        Message.id < latest_inbound_id,
    ).order_by(Message.id.desc()).limit(30).all()
    now = _occurred_at(None)
    for message in candidates:
        metadata = message.metadata_ if isinstance(message.metadata_, dict) else {}
        trace = metadata.get("recommendation")
        request_id = trace.get("request_id") if isinstance(trace, dict) else None
        if not request_id:
            continue
        intervening_outbound = db.query(Message.id).filter(
            Message.conversation_id == conversation_id,
            Message.direction == "outbound",
            Message.id > message.id,
            Message.id < latest_inbound_id,
        ).first()
        if intervening_outbound is not None:
            return False
        request = db.query(RecommendationRequest).filter(
            RecommendationRequest.business_id == business_id,
            RecommendationRequest.request_id == str(request_id),
            RecommendationRequest.customer_id == conversation.customer_id,
        ).first()
        if request is None or request.created_at is None:
            return False
        if _occurred_at(request.created_at) < now - timedelta(days=14):
            return False
        items = [
            item for item in (request.served_items or [])
            if isinstance(item, dict) and str(item.get("product_id", "")).isdigit()
        ]
        if not items:
            return False
        source_message_id = int(latest_inbound_id)
        record_interaction(
            db,
            business_id=business_id,
            customer_id=int(conversation.customer_id),
            product_id=None,
            request_id=request.request_id,
            event_type="slate_skip",
            source="chatbot",
            query=None,
            idempotency_key=f"chat-decline:{request.request_id}:{source_message_id}:slate",
            metadata={
                "source_message_id": source_message_id,
                "signal": "explicit_slate_decline",
                "served_item_count": len(items),
            },
            occurred_at=None,
        )
        db.commit()
        return True
    return False


def record_order_purchase_interactions(db: Session, *, order: Order) -> None:
    """Emit purchase signals exactly once when a sales order is completed."""
    if order.status != "completed":
        return
    consent = db.query(CustomerConsent.status).filter(
        CustomerConsent.business_id == order.business_id,
        CustomerConsent.customer_id == order.customer_id,
        CustomerConsent.purpose == "personalization",
    ).order_by(CustomerConsent.id.desc()).first()
    consent_granted = consent is not None and consent[0] == "granted"
    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).order_by(OrderItem.id.asc()).all()
    for item in items:
        interaction = _existing_or_add(
            db,
            business_id=order.business_id,
            idempotency_key=f"order:{order.id}:purchase:{item.id}",
            values={
                "customer_id": order.customer_id if consent_granted else None,
                "product_id": item.product_id,
                "object_type": "product",
                "recommendation_object_id": str(item.product_id),
                "order_id": order.id,
                "event_type": "purchase",
                "source": "order",
                "query_text": None,
                "event_metadata": {"quantity": int(item.quantity or 0), "order_number": order.order_number},
                "occurred_at": _occurred_at(None),
            },
        )
        request = _recommendation_request_for_order_item(db, order=order, item=item)
        if request is not None:
            interaction.recommendation_request_id = request.id
            interaction.event_metadata = {
                **(interaction.event_metadata or {}),
                **_recommendation_event_snapshot(db, request=request, product_id=int(item.product_id)),
            }
            interaction.model_version = request.model_version
            interaction.catalog_revision = (
                int(interaction.event_metadata["catalog_revision"])
                if str(interaction.event_metadata.get("catalog_revision", "")).isdigit()
                else None
            )
            apply_recommendation_outcome(
                db,
                request=request,
                product_id=int(item.product_id),
                event_type="purchase",
                idempotency_key=f"order:{order.id}:recommendation:{request.id}:{item.product_id}:purchase",
                metadata={"order_id": order.id, "order_number": order.order_number, "attribution": "sent_chat_recommendation"},
            )


def record_order_refund_interactions(db: Session, *, order: Order) -> None:
    """Emit negative product signals only after a fully refunded order."""
    if order.status != "refunded":
        return
    consent = db.query(CustomerConsent.status).filter(
        CustomerConsent.business_id == order.business_id,
        CustomerConsent.customer_id == order.customer_id,
        CustomerConsent.purpose == "personalization",
    ).order_by(CustomerConsent.id.desc()).first()
    consent_granted = consent is not None and consent[0] == "granted"
    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).order_by(OrderItem.id.asc()).all()
    for item in items:
        interaction = _existing_or_add(
            db,
            business_id=order.business_id,
            idempotency_key=f"order:{order.id}:refund:{item.id}",
            values={
                "customer_id": order.customer_id if consent_granted else None,
                "product_id": item.product_id,
                "object_type": "product",
                "recommendation_object_id": str(item.product_id),
                "order_id": order.id,
                "event_type": "refund",
                "source": "order",
                "query_text": None,
                "event_metadata": {"quantity": int(item.quantity or 0), "order_number": order.order_number},
                "occurred_at": _occurred_at(None),
            },
        )
        purchase_interaction = db.query(CustomerProductInteraction).filter(
            CustomerProductInteraction.business_id == order.business_id,
            CustomerProductInteraction.order_id == order.id,
            CustomerProductInteraction.product_id == item.product_id,
            CustomerProductInteraction.event_type == "purchase",
        ).first()
        request_id = purchase_interaction.recommendation_request_id if purchase_interaction else None
        request = db.query(RecommendationRequest).filter(
            RecommendationRequest.business_id == order.business_id,
            RecommendationRequest.id == request_id,
        ).first() if request_id is not None else None
        if request is not None:
            interaction.recommendation_request_id = request.id
            snapshot = _recommendation_event_snapshot(db, request=request, product_id=int(item.product_id))
            interaction.event_metadata = {**(interaction.event_metadata or {}), **snapshot}
            interaction.model_version = request.model_version
            interaction.catalog_revision = (
                int(snapshot["catalog_revision"])
                if str(snapshot.get("catalog_revision", "")).isdigit()
                else None
            )
            apply_recommendation_outcome(
                db,
                request=request,
                product_id=int(item.product_id),
                event_type="refund",
                idempotency_key=f"order:{order.id}:recommendation:{request.id}:{item.product_id}:refund",
                metadata={"order_id": order.id, "order_number": order.order_number, "attribution": "refunded_recommended_product"},
            )


def summarize_interactions(
    db: Session,
    *,
    business_id: int,
    customer_id: int | None,
    days: int,
) -> dict[str, Any]:
    if customer_id is not None:
        customer = db.query(Customer).filter(
            Customer.id == customer_id,
            Customer.business_id == business_id,
        ).first()
        if customer is None:
            raise RecommendationInteractionError("Khách hàng không tồn tại trong shop này.", 404)
    cutoff = _occurred_at(None) - timedelta(days=days)
    query = db.query(CustomerProductInteraction).filter(
        CustomerProductInteraction.business_id == business_id,
        CustomerProductInteraction.occurred_at >= cutoff,
    )
    if customer_id is not None:
        query = query.filter(CustomerProductInteraction.customer_id == customer_id)
    rows = query.order_by(CustomerProductInteraction.id.asc()).all()
    event_counts = Counter(str(row.event_type) for row in rows)
    product_counts = Counter(int(row.product_id) for row in rows if row.product_id is not None)
    return {
        "customer_id": customer_id,
        "days": days,
        "total_events": len(rows),
        "event_counts": dict(sorted(event_counts.items())),
        "top_product_ids": [product_id for product_id, _ in product_counts.most_common(10)],
    }
