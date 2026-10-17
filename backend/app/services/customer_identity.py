"""Resolve channel identities to a tenant-scoped canonical customer."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.customer_collection import CustomerContact
from app.models.customer_identity import CustomerIdentity
from app.models.message import Message
from app.services.audit_service import record_audit
from app.services.customer_profile import (
    merge_profile,
    normalize_name,
    normalize_email,
    normalize_phone,
    profile_change_metadata,
)
from app.services.customer_collection import contact_hash


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


def resolve_conversation_recipient(
    db: Session,
    *,
    conversation_id: int,
    business_id: int,
) -> tuple[str, str]:
    """Resolve the recipient for the conversation's own provider identity."""
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.business_id == business_id,
        )
    )
    if conversation is None:
        raise ValueError("Conversation not found")

    customer = db.scalar(
        select(Customer).where(
            Customer.id == conversation.customer_id,
            Customer.business_id == business_id,
        )
    )
    if customer is None:
        raise ValueError("Conversation customer not found")

    latest_inbound = db.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.channel == conversation.channel,
            Message.direction == "inbound",
        ).order_by(Message.id.desc()).limit(1)
    )

    # Telegram's sender id and destination chat id differ in group chats.
    # Route replies to the chat that produced the latest inbound update.
    if conversation.channel == "telegram" and latest_inbound is not None:
        payload = latest_inbound.raw_payload if isinstance(latest_inbound.raw_payload, dict) else {}
        update_message = payload.get("message") or payload.get("edited_message") or payload
        chat = update_message.get("chat") if isinstance(update_message, dict) else None
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        if chat_id is not None and str(chat_id).strip():
            return conversation.channel, str(chat_id).strip()

    account_id = None
    if conversation.channel_id is not None:
        account_id = db.scalar(
            select(Channel.external_account_id).where(
                Channel.id == conversation.channel_id,
                Channel.business_id == business_id,
                Channel.channel_type == conversation.channel,
            )
        )

    identity_query = select(CustomerIdentity.external_user_id).where(
        CustomerIdentity.business_id == business_id,
        CustomerIdentity.customer_id == customer.id,
        CustomerIdentity.channel == conversation.channel,
    )
    if account_id is not None:
        identity_query = identity_query.where(
            CustomerIdentity.external_account_id == str(account_id)
        )
    identity_id = db.scalar(
        identity_query.order_by(
            CustomerIdentity.last_seen_at.desc(),
            CustomerIdentity.id.desc(),
        ).limit(1)
    )
    if identity_id:
        return conversation.channel, str(identity_id)

    if latest_inbound is not None and latest_inbound.external_user_id:
        return conversation.channel, str(latest_inbound.external_user_id)

    if customer.channel == conversation.channel and customer.external_user_id:
        return conversation.channel, str(customer.external_user_id)

    raise ValueError("No recipient identity exists for the conversation channel")


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
        identity.display_name = normalize_name(display_name) or identity.display_name
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
        # A verified contact collected through checkout/chat is a stronger
        # cross-channel key than a free-form customer field.  Unverified
        # contacts are deliberately ignored so a typo cannot merge profiles.
        if normalized_email:
            contact_customer_id = db.scalar(
                select(CustomerContact.customer_id).where(
                    CustomerContact.business_id == business_id,
                    CustomerContact.kind == "email",
                    CustomerContact.value_hash == contact_hash("email", normalized_email),
                    CustomerContact.verification_status == "verified",
                ).limit(1)
            )
        else:
            contact_customer_id = db.scalar(
                select(CustomerContact.customer_id).where(
                    CustomerContact.business_id == business_id,
                    CustomerContact.kind == "phone",
                    CustomerContact.value_hash == contact_hash("phone", normalized_phone),
                    CustomerContact.verification_status == "verified",
                ).limit(1)
            )
        if contact_customer_id is not None:
            customer = db.scalar(
                select(Customer).where(
                    Customer.id == contact_customer_id,
                    Customer.business_id == business_id,
                )
            )

    if customer is None and (normalized_email or normalized_phone):
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
            display_name=normalize_name(display_name),
        )
    )
    db.commit()
    db.refresh(customer)
    return customer
