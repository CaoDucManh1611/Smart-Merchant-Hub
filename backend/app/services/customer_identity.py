"""Resolve channel identities to a tenant-scoped canonical customer."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.customer_identity import CustomerIdentity


def _clean(value: str | None) -> str | None:
    value = str(value).strip() if value is not None else None
    return value or None


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
        _update_profile(customer, name=name, email=email, phone=phone, avatar_url=avatar_url)
        identity.username = _clean(username) or identity.username
        identity.display_name = _clean(display_name) or identity.display_name
        db.commit()
        db.refresh(customer)
        return customer

    customer = None
    normalized_email = _clean(email)
    normalized_phone = _clean(phone)
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
            name=_clean(name),
            email=normalized_email,
            phone=normalized_phone,
            avatar_url=_clean(avatar_url),
        )
        db.add(customer)
        db.flush()
    else:
        _update_profile(customer, name=name, email=email, phone=phone, avatar_url=avatar_url)

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


def _update_profile(
    customer: Customer,
    *,
    name: str | None,
    email: str | None,
    phone: str | None,
    avatar_url: str | None,
) -> None:
    for field, value in (("name", name), ("email", email), ("phone", phone), ("avatar_url", avatar_url)):
        value = _clean(value)
        if value:
            setattr(customer, field, value)
