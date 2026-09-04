"""Tenant-safe customer profile merge operations."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.customer_fact import CustomerFact
from app.models.customer_identity import CustomerIdentity
from app.models.customer_merge import CustomerMerge
from app.models.customer_note import CustomerNote
from app.models.crm_extended import CustomerTag
from app.models.lead import Lead
from app.models.sales import Order
from app.models.ticket import Ticket
from app.models.purchase_order import PurchaseOrder


COUNT_KEYS = (
    "identities",
    "conversations",
    "notes",
    "facts",
    "tags",
    "leads",
    "tickets",
    "sales_orders",
    "purchase_orders",
)


def _counts(db: Session, customer: Customer) -> dict[str, int]:
    """Return a stable, UI-friendly summary of records owned by a customer."""
    business_id = customer.business_id
    customer_id = customer.id
    counts = {
        "identities": db.query(CustomerIdentity.id).filter(
            CustomerIdentity.business_id == business_id,
            CustomerIdentity.customer_id == customer_id,
        ).count(),
        "conversations": db.query(Conversation.id).filter(
            Conversation.business_id == business_id,
            Conversation.customer_id == customer_id,
        ).count(),
        "notes": db.query(CustomerNote.id).filter(
            CustomerNote.business_id == business_id,
            CustomerNote.customer_id == customer_id,
        ).count(),
        "facts": db.query(CustomerFact.id).filter(
            CustomerFact.business_id == business_id,
            CustomerFact.customer_id == customer_id,
        ).count(),
        "tags": db.query(CustomerTag.id).filter(
            CustomerTag.business_id == business_id,
            CustomerTag.customer_id == customer_id,
        ).count(),
        "leads": db.query(Lead.id).filter(
            Lead.business_id == business_id,
            Lead.customer_id == customer_id,
        ).count(),
        "tickets": db.query(Ticket.id).filter(
            Ticket.business_id == business_id,
            Ticket.customer_id == customer_id,
        ).count(),
        "sales_orders": db.query(Order.id).filter(
            Order.business_id == business_id,
            Order.customer_id == customer_id,
        ).count(),
        # Purchase orders are shop-level records.  Count only records that an
        # operator explicitly linked to this customer via metadata.customer_id.
        "purchase_orders": sum(
            1
            for purchase in db.query(PurchaseOrder).filter(
                PurchaseOrder.business_id == business_id,
            ).all()
            if isinstance(purchase.metadata_, dict)
            and str(purchase.metadata_.get("customer_id", "")) == str(customer_id)
        ),
    }
    return {key: int(counts.get(key, 0)) for key in COUNT_KEYS}


def _customer_pair(
    db: Session,
    survivor_customer_id: int,
    source_customer_id: int,
    business_id: int,
) -> tuple[Customer, Customer]:
    if survivor_customer_id == source_customer_id:
        raise HTTPException(status_code=422, detail="Không thể gộp customer vào chính nó.")
    customers = db.query(Customer).filter(
        Customer.business_id == business_id,
        Customer.id.in_([survivor_customer_id, source_customer_id]),
    ).all()
    by_id = {customer.id: customer for customer in customers}
    survivor = by_id.get(survivor_customer_id)
    source = by_id.get(source_customer_id)
    if survivor is None or source is None:
        raise HTTPException(status_code=404, detail="Customer không tồn tại trong business này.")
    if source.status == "merged":
        raise HTTPException(status_code=409, detail="Customer nguồn đã được gộp trước đó.")
    return survivor, source


def preview_merge(
    db: Session,
    survivor_customer_id: int,
    source_customer_id: int,
    business_id: int,
) -> tuple[Customer, Customer, dict[str, int], dict[str, int]]:
    survivor, source = _customer_pair(
        db, survivor_customer_id, source_customer_id, business_id
    )
    return survivor, source, _counts(db, survivor), _counts(db, source)


def _reassign_rows(
    db: Session,
    model: type,
    business_id: int,
    source_id: int,
    survivor_id: int,
) -> None:
    rows = db.query(model).filter(
        model.business_id == business_id,
        model.customer_id == source_id,
    ).all()
    for row in rows:
        row.customer_id = survivor_id


def _reassign_identities(
    db: Session,
    business_id: int,
    source_id: int,
    survivor_id: int,
) -> None:
    identities = db.query(CustomerIdentity).filter(
        CustomerIdentity.business_id == business_id,
        CustomerIdentity.customer_id == source_id,
    ).all()
    for identity in identities:
        duplicate = db.query(CustomerIdentity.id).filter(
            CustomerIdentity.business_id == business_id,
            CustomerIdentity.customer_id == survivor_id,
            CustomerIdentity.channel == identity.channel,
            CustomerIdentity.external_account_id == identity.external_account_id,
            CustomerIdentity.external_user_id == identity.external_user_id,
            CustomerIdentity.id != identity.id,
        ).first()
        if duplicate is not None:
            db.delete(identity)
        else:
            identity.customer_id = survivor_id


def _reassign_tags(
    db: Session,
    business_id: int,
    source_id: int,
    survivor_id: int,
) -> None:
    links = db.query(CustomerTag).filter(
        CustomerTag.business_id == business_id,
        CustomerTag.customer_id == source_id,
    ).all()
    for link in links:
        duplicate = db.query(CustomerTag.id).filter(
            CustomerTag.business_id == business_id,
            CustomerTag.customer_id == survivor_id,
            CustomerTag.tag_id == link.tag_id,
            CustomerTag.id != link.id,
        ).first()
        if duplicate is not None:
            db.delete(link)
        else:
            link.customer_id = survivor_id


def _reassign_linked_purchase_orders(
    db: Session,
    business_id: int,
    source_id: int,
    survivor_id: int,
) -> None:
    """Move explicitly customer-linked procurement records during a merge."""
    purchases = db.query(PurchaseOrder).filter(
        PurchaseOrder.business_id == business_id,
    ).all()
    for purchase in purchases:
        metadata = purchase.metadata_
        if not isinstance(metadata, dict) or str(metadata.get("customer_id", "")) != str(source_id):
            continue
        purchase.metadata_ = {**metadata, "customer_id": survivor_id}


def merge_customer(
    db: Session,
    survivor_customer_id: int,
    source_customer_id: int,
    business_id: int,
    reason: str | None = None,
    created_by: int | None = None,
) -> CustomerMerge:
    survivor, source = _customer_pair(
        db, survivor_customer_id, source_customer_id, business_id
    )
    existing = db.query(CustomerMerge.id).filter(
        CustomerMerge.business_id == business_id,
        CustomerMerge.survivor_customer_id == survivor.id,
        CustomerMerge.source_customer_id == source.id,
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Hai customer này đã được gộp.")

    before_counts = _counts(db, source)
    _reassign_identities(db, business_id, source.id, survivor.id)
    _reassign_tags(db, business_id, source.id, survivor.id)
    for model in (
        Conversation,
        CustomerNote,
        CustomerFact,
        Lead,
        Ticket,
        Order,
    ):
        _reassign_rows(db, model, business_id, source.id, survivor.id)
    _reassign_linked_purchase_orders(db, business_id, source.id, survivor.id)

    source.status = "merged"
    source.merged_into_customer_id = survivor.id
    db.flush()
    after_counts = _counts(db, survivor)
    merge = CustomerMerge(
        business_id=business_id,
        survivor_customer_id=survivor.id,
        source_customer_id=source.id,
        reason=reason.strip() if reason and reason.strip() else None,
        before_counts=before_counts,
        after_counts=after_counts,
        created_by=created_by,
    )
    db.add(merge)
    db.commit()
    db.refresh(merge)
    return merge
