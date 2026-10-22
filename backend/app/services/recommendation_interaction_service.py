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
from app.models.sales import Order, OrderItem, Product


PRODUCT_REQUIRED_EVENTS = {"view", "impression", "click", "cart", "purchase", "skip", "refund"}


class RecommendationInteractionError(ValueError):
    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


_FEEDBACK_REWARDS = {
    "impression": Decimal("0"),
    "click": Decimal("0.2"),
    "cart": Decimal("0.5"),
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
    feedback = RecommendationFeedback(
        business_id=request.business_id,
        recommendation_request_id=request.id,
        product_id=product_id,
        event_type=event_type,
        reward=reward,
        idempotency_key=idempotency_key,
        event_metadata=metadata or {},
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


def record_interaction(
    db: Session,
    *,
    business_id: int,
    customer_id: int | None,
    product_id: int | None,
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
    if normalized_event in PRODUCT_REQUIRED_EVENTS and product_id is None:
        raise RecommendationInteractionError("Loại interaction này cần product_id.")
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
        if latest_consent is not None and latest_consent.status == "revoked":
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

    row = _existing_or_add(
        db,
        business_id=business_id,
        idempotency_key=idempotency_key.strip(),
        values={
            "customer_id": customer_id,
            "product_id": product_id,
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
) -> None:
    """Record each served item once, within the request transaction."""
    for item in request.served_items or []:
        product_id = item.get("product_id")
        if not isinstance(product_id, int):
            continue
        _existing_or_add(
            db,
            business_id=request.business_id,
            idempotency_key=f"recommendation:{request.request_id}:impression:{product_id}",
            values={
                "customer_id": request.customer_id,
                "product_id": product_id,
                "recommendation_request_id": request.id,
                "event_type": "impression",
                "source": "recommendation",
                "query_text": None,
                "event_metadata": {"strategy": request.strategy, "model_version": request.model_version},
                "occurred_at": _occurred_at(None),
            },
        )


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
    folded = "".join(
        char for char in unicodedata.normalize("NFKD", str(text or "").lower())
        if not unicodedata.combining(char)
    )
    folded = folded.replace("’", "'").replace("'", "")
    folded = " ".join("".join(char if char.isalnum() or char.isspace() else " " for char in folded).split())
    decline_phrases = (
        "khong thich", "khong hop", "khong phu hop", "khong lay", "khong can",
        "khong mua", "khong ung", "thoi khong", "bo qua", "not interested", "not a fit",
        "not for me", "do not want", "dont want", "dont like", "no thanks", "ill pass", "i will pass",
    )
    if not any(phrase in folded for phrase in decline_phrases):
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
    if consent is not None and consent[0] == "revoked":
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
        chosen = items[0]
        product_id = int(chosen["product_id"])
        source_message_id = int(latest_inbound_id)
        record_interaction(
            db,
            business_id=business_id,
            customer_id=int(conversation.customer_id),
            product_id=product_id,
            request_id=request.request_id,
            event_type="skip",
            source="chatbot",
            query=None,
            idempotency_key=f"chat-decline:{request.request_id}:{source_message_id}:{product_id}",
            metadata={"source_message_id": source_message_id, "signal": "explicit_decline"},
            occurred_at=None,
        )
        apply_recommendation_outcome(
            db,
            request=request,
            product_id=product_id,
            event_type="skip",
            idempotency_key=f"chat-decline:{request.request_id}:{source_message_id}:{product_id}",
            metadata={"source_message_id": source_message_id, "signal": "explicit_decline"},
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
    if consent and consent[0] == "revoked":
        return
    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).order_by(OrderItem.id.asc()).all()
    for item in items:
        interaction = _existing_or_add(
            db,
            business_id=order.business_id,
            idempotency_key=f"order:{order.id}:purchase:{item.id}",
            values={
                "customer_id": order.customer_id,
                "product_id": item.product_id,
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
    if consent and consent[0] == "revoked":
        return
    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).order_by(OrderItem.id.asc()).all()
    for item in items:
        interaction = _existing_or_add(
            db,
            business_id=order.business_id,
            idempotency_key=f"order:{order.id}:refund:{item.id}",
            values={
                "customer_id": order.customer_id,
                "product_id": item.product_id,
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
