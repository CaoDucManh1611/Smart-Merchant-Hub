from sqlalchemy import select
from sqlalchemy.orm import Session

from decimal import Decimal
import re

from app.models.business import Business, ServicePlan


DEFAULT_BUSINESS_SLUG = "default-business"
DEFAULT_BUSINESS_NAME = "Default Business"


def ensure_default_business(db: Session) -> Business:
    """Return the built-in tenant, creating it once when absent."""
    business = db.scalar(
        select(Business).where(Business.slug == DEFAULT_BUSINESS_SLUG)
    )
    if business is not None:
        return business

    business = Business(
        name=DEFAULT_BUSINESS_NAME,
        slug=DEFAULT_BUSINESS_SLUG,
        status="active",
    )
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


DEFAULT_PLANS = (
    {
        "code": "demo",
        "name": "Gói Demo",
        "description": "Gói dùng thử 0 đồng để xem giao diện và quy trình CRM. Chưa mở kết nối mạng xã hội.",
        "price": Decimal("0"),
        "max_users": 1,
        "max_channels": 0,
        "max_documents": 0,
        "max_rag_chunks": 0,
        "max_ai_calls": 50,
        "max_ai_cost": Decimal("0"),
        "features": {"onboarding": True, "support": "email", "display_name": "Gói Demo", "demo_only": True, "chatbot_rental_price": 0},
    },
    {
        "code": "starter",
        "name": "Gói Thường",
        "description": "Gói gọn nhẹ cho shop mới bắt đầu chăm khách và quản lý hội thoại.",
        # Keep the starter tier free for local/demo onboarding. Paid tiers
        # still require an explicit purchase, while a new shop can connect
        # one channel and exercise the CRM flow immediately.
        "price": Decimal("0"),
        "max_users": 3,
        "max_channels": 1,
        "max_documents": 10,
        "max_rag_chunks": 250,
        "max_ai_calls": 500,
        "max_ai_cost": Decimal("25"),
        "features": {"onboarding": True, "support": "email", "display_name": "Gói Thường", "chatbot_rental_price": 100000},
    },
    {
        "code": "growth",
        "name": "Gói VIP",
        "description": "Gói cân bằng cho shop cần nhiều kênh và đội ngũ chăm khách hằng ngày.",
        "price": Decimal("400000"),
        "max_users": 10,
        "max_channels": 2,
        "max_documents": 50,
        "max_rag_chunks": 2000,
        "max_ai_calls": 5000,
        "max_ai_cost": Decimal("250"),
        "features": {"onboarding": True, "support": "priority", "display_name": "Gói VIP", "chatbot_rental_price": 400000},
    },
    {
        "code": "pro",
        "name": "Gói Premium",
        "description": "Gói đầy đủ cho shop vận hành đa kênh với hạn mức cao hơn.",
        "price": Decimal("1000000"),
        "max_users": 50,
        "max_channels": 4,
        "max_documents": 200,
        "max_rag_chunks": 10000,
        "max_ai_calls": 25000,
        "max_ai_cost": Decimal("1000"),
        "features": {"onboarding": True, "support": "dedicated", "display_name": "Gói Premium", "chatbot_rental_price": 1000000},
    },
)


def ensure_default_plans(db: Session) -> list[ServicePlan]:
    """Seed the customer-facing catalogue without undoing administrator edits.

    Stable internal codes keep existing subscriptions and foreign keys valid,
    while missing default feature keys are repaired on older databases.  Plan
    prices and quotas are administrator-owned after creation, so querying the
    catalogue must never reset a deliberate edit.
    """
    existing_by_code = {
        plan.code: plan
        for plan in db.query(ServicePlan).order_by(ServicePlan.id.asc()).all()
    }
    plans: list[ServicePlan] = []
    for payload in DEFAULT_PLANS:
        plan = existing_by_code.get(payload["code"])
        if plan is None:
            plan = ServicePlan(**payload)
            db.add(plan)
        else:
            existing_features = dict(plan.features or {})
            missing_features = {
                key: value
                for key, value in dict(payload["features"]).items()
                if key not in existing_features
            }
            if missing_features:
                plan.features = {**existing_features, **missing_features}
        plans.append(plan)
    db.flush()
    return plans
