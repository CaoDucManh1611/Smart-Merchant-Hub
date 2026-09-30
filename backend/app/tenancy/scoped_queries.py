"""Small tenant predicates for service/repository boundaries."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.customer import Customer


def get_customer_for_tenant(
    db: Session,
    customer_id: int,
    business_id: int,
) -> Customer | None:
    """Fetch a customer only when it belongs to the requested tenant."""
    return db.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.business_id == business_id,
        )
    )
