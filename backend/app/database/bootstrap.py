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
        "code": "starter",
        "name": "Starter",
        "description": "Cho shop mới bắt đầu vận hành đa kênh.",
        "price": Decimal("0"),
        "max_users": 3,
        "max_channels": 2,
        "max_documents": 10,
        "max_rag_chunks": 250,
        "max_ai_calls": 500,
        "max_ai_cost": Decimal("25"),
        "features": {"onboarding": True, "support": "community"},
    },
    {
        "code": "growth",
        "name": "Growth",
        "description": "Cho shop đang tăng trưởng và cần tự động hóa.",
        "price": Decimal("499000"),
        "max_users": 10,
        "max_channels": 4,
        "max_documents": 50,
        "max_rag_chunks": 2000,
        "max_ai_calls": 5000,
        "max_ai_cost": Decimal("250"),
        "features": {"onboarding": True, "support": "priority"},
    },
    {
        "code": "pro",
        "name": "Pro",
        "description": "Cho đội ngũ lớn và nhu cầu AI cao.",
        "price": Decimal("1499000"),
        "max_users": 50,
        "max_channels": 10,
        "max_documents": 200,
        "max_rag_chunks": 10000,
        "max_ai_calls": 25000,
        "max_ai_cost": Decimal("1000"),
        "features": {"onboarding": True, "support": "dedicated"},
    },
)


def ensure_default_plans(db: Session) -> list[ServicePlan]:
    """Seed safe, free-to-read plans for a fresh self-service deployment."""
    existing = db.query(ServicePlan).order_by(ServicePlan.id.asc()).all()
    if existing:
        return existing
    plans = [ServicePlan(**payload) for payload in DEFAULT_PLANS]
    db.add_all(plans)
    db.flush()
    return plans
