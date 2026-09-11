"""Tenant-scoped customer export and privacy-preserving lifecycle actions."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.customer_collection import CustomerAddress, CustomerContact
from app.models.customer_fact import CustomerFact
from app.models.customer_identity import CustomerIdentity
from app.models.customer_note import CustomerNote
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.sales import Order
from app.models.saas import DataLifecycleRequest


def get_or_create_request(
    db: Session,
    *,
    business_id: int,
    request_key: str,
    kind: str,
    requested_by: int | None,
) -> tuple[DataLifecycleRequest, bool]:
    row = db.scalar(
        select(DataLifecycleRequest).where(
            DataLifecycleRequest.business_id == business_id,
            DataLifecycleRequest.request_key == request_key,
        )
    )
    if row is not None:
        if row.kind != kind:
            raise ValueError("request_key đã được dùng cho tác vụ khác")
        return row, False
    row = DataLifecycleRequest(
        business_id=business_id,
        request_key=request_key,
        kind=kind,
        status="processing",
        requested_by=requested_by,
    )
    db.add(row)
    db.flush()
    return row, True


def _customer_rows(db: Session, business_id: int) -> list[Customer]:
    return db.scalars(
        select(Customer).where(Customer.business_id == business_id).order_by(Customer.id.asc())
    ).all()


def export_customer_data(db: Session, business_id: int) -> tuple[dict, dict[str, int]]:
    customers = _customer_rows(db, business_id)
    payload = {"business_id": business_id, "customers": []}
    conversation_count = 0
    message_count = 0
    order_count = 0
    for customer in customers:
        conversations = db.scalars(
            select(Conversation).where(
                Conversation.business_id == business_id,
                Conversation.customer_id == customer.id,
            ).order_by(Conversation.id.asc())
        ).all()
        conversation_data = []
        for conversation in conversations:
            messages = db.scalars(
                select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id.asc())
            ).all()
            message_count += len(messages)
            conversation_data.append({
                "id": conversation.id,
                "channel": conversation.channel,
                "status": conversation.status,
                "messages": [
                    {
                        "id": message.id,
                        "direction": message.direction,
                        "sender_type": message.sender_type,
                        "content": message.content,
                        "received_at": message.received_at.isoformat() if message.received_at else None,
                    }
                    for message in messages
                ],
            })
        orders = db.scalars(
            select(Order).where(
                Order.business_id == business_id,
                Order.customer_id == customer.id,
            ).order_by(Order.id.asc())
        ).all()
        order_count += len(orders)
        payload["customers"].append({
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "phone": customer.phone,
            "address": customer.address,
            "channel": customer.channel,
            "external_user_id": customer.external_user_id,
            "identities": [
                {
                    "channel": identity.channel,
                    "external_account_id": identity.external_account_id,
                    "external_user_id": identity.external_user_id,
                    "username": identity.username,
                    "display_name": identity.display_name,
                }
                for identity in customer.identities
            ],
            "conversations": conversation_data,
            "orders": [
                {
                    "id": order.id,
                    "order_number": order.order_number,
                    "status": order.status,
                    "total_amount": float(order.total_amount or 0),
                    "shipping_address": order.shipping_address,
                    "shipping_phone": order.shipping_phone,
                }
                for order in orders
            ],
        })
        conversation_count += len(conversations)
    return payload, {
        "customers": len(customers),
        "conversations": conversation_count,
        "messages": message_count,
        "orders": order_count,
    }


def _anonymize_customer(db: Session, customer: Customer, *, deleted: bool) -> dict[str, int]:
    marker = f"customer-{customer.id}"
    customer.name = "Khách hàng đã ẩn danh"
    customer.email = None
    customer.phone = None
    customer.address = None
    customer.avatar_url = None
    customer.external_user_id = f"anon-{marker}"
    customer.status = "deleted" if deleted else "anonymized"
    for identity in customer.identities:
        identity.external_user_id = f"anon-{marker}-{identity.id}"
        identity.username = None
        identity.display_name = None
    for contact in customer.contacts:
        contact.value_encrypted = "[REDACTED]"
        contact.value_hash = f"redacted-{contact.id}"
        contact.masked_value = "[REDACTED]"
        contact.verification_status = "redacted"
    for address in customer.addresses:
        address.recipient_name = None
        address.phone = None
        address.address_line1 = "[REDACTED]"
        address.address_line2 = None
        address.ward = None
        address.district = None
        address.province = None
        address.postal_code = None
    for fact in customer.facts:
        fact.fact_value_json = {"redacted": True}
    for note in db.scalars(select(CustomerNote).where(CustomerNote.customer_id == customer.id)).all():
        note.content = "[REDACTED]"
    conversations = db.scalars(select(Conversation).where(Conversation.business_id == customer.business_id, Conversation.customer_id == customer.id)).all()
    message_count = 0
    for conversation in conversations:
        messages = db.scalars(select(Message).where(Message.conversation_id == conversation.id)).all()
        message_count += len(messages)
        for message in messages:
            message.content = "[REDACTED]"
            message.media_url = None
            message.raw_payload = None
            message.metadata_ = None
    orders = db.scalars(select(Order).where(Order.business_id == customer.business_id, Order.customer_id == customer.id)).all()
    for order in orders:
        order.shipping_address = None
        order.shipping_phone = None
    return {"customers": 1, "conversations": len(conversations), "messages": message_count, "orders": len(orders)}


def anonymize_customer_data(db: Session, business_id: int, *, deleted: bool = False) -> dict[str, int]:
    totals = {"customers": 0, "conversations": 0, "messages": 0, "orders": 0}
    for customer in _customer_rows(db, business_id):
        counts = _anonymize_customer(db, customer, deleted=deleted)
        for key, value in counts.items():
            totals[key] += value
    return totals


def complete_request(row: DataLifecycleRequest, *, counts: dict[str, int]) -> None:
    row.status = "completed"
    row.result_metadata = {"counts": counts}
    row.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
