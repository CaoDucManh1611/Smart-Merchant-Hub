"""Tenant-safe behavioral event ingestion for product recommendations."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.recommendation import (
    CustomerProductInteraction,
    RecommendationRequest,
)
from app.models.sales import Order, OrderItem, Product


PRODUCT_REQUIRED_EVENTS = {"view", "impression", "click", "cart", "purchase", "skip", "refund"}


class RecommendationInteractionError(ValueError):
    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


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


def record_order_purchase_interactions(db: Session, *, order: Order) -> None:
    """Emit purchase signals exactly once when a sales order is completed."""
    if order.status != "completed":
        return
    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).order_by(OrderItem.id.asc()).all()
    for item in items:
        _existing_or_add(
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


def record_order_refund_interactions(db: Session, *, order: Order) -> None:
    """Emit negative product signals only after a fully refunded order."""
    if order.status != "refunded":
        return
    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).order_by(OrderItem.id.asc()).all()
    for item in items:
        _existing_or_add(
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
