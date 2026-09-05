"""Resolve channel identities to a tenant-scoped canonical customer."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.customer_identity import CustomerIdentity
from app.services.audit_service import record_audit
from app.services.customer_profile import (
    merge_profile,
    normalize_name,
    normalize_email,
    normalize_phone,
    profile_change_metadata,
)


def _clean(value: str | None) -> str | None:
    value = str(value).strip() if value is not None else None
    return value or None


def get_existing_name_priority(db: Session, customer: Customer) -> int:
    """Recover the best-known source rank for a stored customer name.

    Customer rows predate the source-rank column, so the associated immutable
    identities are the trustworthy record of whether the current value came
    from a display name (3), a username (1), or an ordinary name (2).
    """
    current = normalize_name(customer.name)
    if not current:
        return 0
    identities = db.scalars(
        select(CustomerIdentity).where(
            CustomerIdentity.business_id == customer.business_id,
            CustomerIdentity.customer_id == customer.id,
        )
    ).all()
    if any(normalize_name(identity.display_name) == current for identity in identities):
        return 3
    if any(normalize_name(identity.username) == current for identity in identities):
        return 1
    return 2


def resolve_customer(
    db: Session,
    business_id: int,
    channel: str,
    external_user_id: str,
    external_account_id: str | None = None,
    *,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    avatar_url: str | None = None,
    username: str | None = None,
    display_name: str | None = None,
) -> Customer:
    """Find or create a customer and attach the incoming channel identity.

    Matching is deliberately tenant-scoped. Exact platform identity wins;
    email/phone are fallback keys supplied by a trusted channel or operator.
    Names are never used as an automatic merge key.
    """
    channel = _clean(channel)
    external_user_id = _clean(external_user_id)
    external_account_id = _clean(external_account_id) or ""
    if not channel or not external_user_id:
        raise ValueError("channel and external_user_id are required")

    identity = db.scalar(
        select(CustomerIdentity).where(
            CustomerIdentity.business_id == business_id,
            CustomerIdentity.channel == channel,
            CustomerIdentity.external_account_id == external_account_id,
            CustomerIdentity.external_user_id == external_user_id,
        )
    )
    if identity is not None:
        customer = identity.customer
        changes = merge_profile(
            customer,
            existing_name_priority=get_existing_name_priority(db, customer),
            name=name,
            display_name=display_name,
            username=username,
            email=email,
            phone=phone,
            avatar_url=avatar_url,
        )
        identity.username = _clean(username) or identity.username
        identity.display_name = _clean(display_name) or identity.display_name
        if changes:
            record_audit(
                db,
                business_id=business_id,
                action="profile_update",
                resource_type="customer",
                resource_id=customer.id,
                metadata=profile_change_metadata(changes),
            )
        db.commit()
        db.refresh(customer)
        return customer

    customer = None
    normalized_email = normalize_email(email)
    normalized_phone = normalize_phone(phone)
    if normalized_email or normalized_phone:
        candidates = select(Customer).where(Customer.business_id == business_id)
        if normalized_email:
            candidates = candidates.where(Customer.email == normalized_email)
        elif normalized_phone:
            candidates = candidates.where(Customer.phone == normalized_phone)
        customer = db.scalar(candidates.limit(1))

    if customer is None:
        customer = Customer(
            business_id=business_id,
            channel=channel,
            external_user_id=external_user_id,
            name=None,
            email=None,
            phone=None,
            avatar_url=None,
        )
        db.add(customer)
        db.flush()
        changes = merge_profile(
            customer,
            existing_name_priority=get_existing_name_priority(db, customer),
            name=name,
            display_name=display_name,
            username=username,
            email=normalized_email,
            phone=normalized_phone,
            avatar_url=avatar_url,
        )
        record_audit(
            db,
            business_id=business_id,
            action="profile_created",
            resource_type="customer",
            resource_id=customer.id,
            metadata=profile_change_metadata(changes),
        )
    else:
        changes = merge_profile(
            customer,
            existing_name_priority=get_existing_name_priority(db, customer),
            name=name,
            display_name=display_name,
            username=username,
            email=email,
            phone=phone,
            avatar_url=avatar_url,
        )
        if changes:
            record_audit(
                db,
                business_id=business_id,
                action="profile_update",
                resource_type="customer",
                resource_id=customer.id,
                metadata=profile_change_metadata(changes),
            )

    db.add(
        CustomerIdentity(
            business_id=business_id,
            customer_id=customer.id,
            channel=channel,
            external_account_id=external_account_id,
            external_user_id=external_user_id,
            username=_clean(username),
            display_name=_clean(display_name),
        )
    )
    db.commit()
    db.refresh(customer)
    return customer
