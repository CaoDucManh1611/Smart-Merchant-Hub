"""Shared definitions for completed-order analytics."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, or_

from app.models.sales import Order


def completed_order_conditions(as_of: datetime | None = None) -> tuple:
    """Only count completed orders or paid deliveries, net of full refunds."""
    cutoff = as_of or datetime.now(timezone.utc).replace(tzinfo=None)
    return (
        or_(
            Order.status == "completed",
            and_(Order.status == "delivered", Order.payment_status == "paid"),
        ),
        Order.payment_status.notin_(("refunded", "failed")),
        Order.total_amount > Order.refunded_amount,
        Order.created_at <= cutoff,
    )


def net_order_value(order: Order) -> Decimal:
    """Return the remaining order value after refunds."""
    return max(
        Decimal("0"),
        Decimal(order.total_amount or 0) - Decimal(order.refunded_amount or 0),
    )


def net_order_amount_expression():
    """SQL expression for aggregating order value after partial refunds."""
    return Order.total_amount - Order.refunded_amount
