"""Shared, explainable RFM labels for CRM and recommendation profiles."""

from datetime import datetime, timezone
from bisect import bisect_left, bisect_right

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.sales import Order, OrderItem
from app.services.order_metrics import completed_order_conditions, net_order_amount_expression

RFM_RULES_VERSION = "rfm_percentile_v1"

RFM_GROUPS = (
    "RFM · Khách mới",
    "RFM · Chưa mua",
    "RFM · Giá trị cao",
    "RFM · Trung thành",
    "RFM · Tiềm năng",
    "RFM · Cần chăm sóc",
    "RFM · Nguy cơ rời bỏ",
    "RFM · Duy trì",
)

RFM_SEGMENT_KEYS = {
    "RFM · Khách mới": "new_customer",
    "RFM · Chưa mua": "no_purchase",
    "RFM · Giá trị cao": "high_value",
    "RFM · Trung thành": "loyal",
    "RFM · Tiềm năng": "potential",
    "RFM · Cần chăm sóc": "needs_attention",
    "RFM · Nguy cơ rời bỏ": "at_risk",
    "RFM · Duy trì": "regular",
}


def rfm_score(value: float, population: list[float], *, lower_is_better: bool = False) -> int:
    return _sorted_rfm_score(value, sorted(population), lower_is_better=lower_is_better)


def _sorted_rfm_score(value: float, population: list[float], *, lower_is_better: bool = False) -> int:
    if not population:
        return 1
    if len(population) == 1:
        return 3
    left, right = bisect_left(population, value), bisect_right(population, value)
    rank = left + (right - left - 1) / 2
    if lower_is_better:
        rank = len(population) - 1 - rank
    return max(1, min(5, 1 + round(4 * rank / (len(population) - 1))))


def rfm_group(recency: int, frequency: int, monetary: float, *, first_purchase_recent: bool = False) -> str:
    if frequency == 0:
        return "RFM · Chưa mua"
    if first_purchase_recent:
        return "RFM · Khách mới"
    if recency >= 4 and frequency >= 4 and monetary >= 4:
        return "RFM · Giá trị cao"
    if recency >= 3 and frequency >= 4:
        return "RFM · Trung thành"
    if recency >= 4 and frequency <= 2:
        return "RFM · Tiềm năng"
    if recency <= 2 and frequency >= 3:
        return "RFM · Cần chăm sóc"
    if recency <= 2 and frequency <= 2:
        return "RFM · Nguy cơ rời bỏ"
    return "RFM · Duy trì"


def customer_rfm_profiles(db: Session, business_id: int, *, as_of: datetime | None = None) -> dict[int, dict]:
    """One tenant-wide buyer population for both CRM labels and recommendations.

    Order totals are aggregated separately from lines, so a multi-item order
    contributes once to frequency and monetary. No-purchase customers are not
    included in the percentile population.
    """
    now = as_of or datetime.now(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    customer_ids = db.query(Customer.id).filter(
        Customer.business_id == business_id, Customer.status != "merged",
    ).all()
    profiles = {
        int(customer_id): {
            "customer_id": int(customer_id), "recency_days": 365, "frequency": 0,
            "monetary": 0.0, "total_items": 0, "distinct_products": 0, "avg_order_value": 0.0,
        }
        for (customer_id,) in customer_ids
    }
    if not profiles:
        return profiles
    conditions = (
        Order.business_id == business_id, Order.customer_id.in_(profiles),
        *completed_order_conditions(now),
    )
    rows = db.query(
        Order.customer_id, func.count(Order.id), func.sum(net_order_amount_expression()), func.max(Order.created_at),
    ).filter(*conditions).group_by(Order.customer_id).all()
    for customer_id, frequency, monetary, latest in rows:
        profile = profiles[int(customer_id)]
        profile.update(
            frequency=int(frequency), monetary=float(monetary or 0),
            recency_days=max(0, (now - latest.replace(tzinfo=None)).days) if latest else 365,
            avg_order_value=float(monetary or 0) / max(1, int(frequency)),
        )
    items = db.query(
        Order.customer_id, func.sum(OrderItem.quantity), func.count(func.distinct(OrderItem.product_id)),
    ).join(Order, Order.id == OrderItem.order_id).filter(*conditions).group_by(Order.customer_id).all()
    for customer_id, total_items, distinct_products in items:
        profiles[int(customer_id)].update(total_items=int(total_items or 0), distinct_products=int(distinct_products or 0))
    buyers = [profile for profile in profiles.values() if profile["frequency"] > 0]
    populations = {key: sorted(float(p[key]) for p in buyers) for key in ("recency_days", "frequency", "monetary")}
    for profile in profiles.values():
        scores = None
        name = "RFM · Chưa mua"
        if profile["frequency"]:
            scores = {
                "recency": _sorted_rfm_score(float(profile["recency_days"]), populations["recency_days"], lower_is_better=True),
                "frequency": _sorted_rfm_score(float(profile["frequency"]), populations["frequency"]),
                "monetary": _sorted_rfm_score(float(profile["monetary"]), populations["monetary"]),
            }
            name = rfm_group(
                scores["recency"], scores["frequency"], scores["monetary"],
                first_purchase_recent=profile["frequency"] == 1 and profile["recency_days"] <= 30,
            )
        profile.update(segment_label=RFM_SEGMENT_KEYS[name], segment_name=name, rfm_scores=scores)
    return profiles
