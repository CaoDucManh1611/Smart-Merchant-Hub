from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.business import Business


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
