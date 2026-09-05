"""Tenant-safe customer profile merge operations."""

from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
import unicodedata

from fastapi import HTTPException
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Table,
    Text,
    func,
    select,
    update,
)
from sqlalchemy.orm import Session

from app.database.session import Base
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


customer_merge_operations = Table(
    "customer_merge_operations",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("business_id", Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("customer_merge_id", Integer, ForeignKey("customer_merges.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
    Column("status", String(20), nullable=False, server_default="completed", index=True),
    Column("confidence_score", Numeric(5, 4), nullable=True),
    Column("evidence", JSON, nullable=False, default=dict),
    Column("moved_records", JSON, nullable=False, default=dict),
    Column("confirmed_at", DateTime, nullable=True),
    Column("undone_at", DateTime, nullable=True),
    Column("undone_by", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("undo_reason", Text, nullable=True),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
)


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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalized(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value).strip().lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _normalized_phone(value: str | None) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def duplicate_evidence(
    db: Session,
    first: Customer,
    second: Customer,
) -> dict:
    """Score duplicate candidates using explainable, deterministic signals."""
    score = 0.0
    matched_fields: list[str] = []
    evidence: list[dict] = []

    first_email = _normalized(first.email)
    second_email = _normalized(second.email)
    if first_email and second_email and first_email == second_email:
        score += 0.45
        matched_fields.append("email")
        evidence.append({"field": "email", "weight": 0.45, "reason": "Email trùng khớp."})

    first_phone = _normalized_phone(first.phone)
    second_phone = _normalized_phone(second.phone)
    if first_phone and second_phone and first_phone == second_phone:
        score += 0.35
        matched_fields.append("phone")
        evidence.append({"field": "phone", "weight": 0.35, "reason": "Số điện thoại trùng khớp."})

    first_name = _normalized(first.name)
    second_name = _normalized(second.name)
    if first_name and second_name:
        ratio = SequenceMatcher(None, first_name, second_name).ratio()
        if ratio >= 0.85:
            score += 0.15
            matched_fields.append("name")
            evidence.append({"field": "name", "weight": 0.15, "similarity": round(ratio, 4), "reason": "Tên gần như trùng khớp."})
        elif ratio >= 0.7:
            score += 0.08
            matched_fields.append("name_similar")
            evidence.append({"field": "name", "weight": 0.08, "similarity": round(ratio, 4), "reason": "Tên có độ tương đồng."})

    first_address = _normalized(first.address)
    second_address = _normalized(second.address)
    if first_address and second_address and first_address == second_address:
        score += 0.05
        matched_fields.append("address")
        evidence.append({"field": "address", "weight": 0.05, "reason": "Địa chỉ trùng khớp."})

    if first.channel == second.channel and first.external_user_id == second.external_user_id:
        score += 0.2
        matched_fields.append("channel_identity")
        evidence.append({"field": "channel_identity", "weight": 0.2, "reason": "Định danh kênh trùng khớp."})

    score = round(min(score, 1.0), 4)
    label = "high" if score >= 0.8 else "medium" if score >= 0.55 else "low"
    return {
        "confidence_score": score,
        "confidence_label": label,
        "matched_fields": matched_fields,
        "evidence": evidence,
    }


def find_duplicate_suggestions(
    db: Session,
    business_id: int,
    *,
    customer_id: int | None = None,
    threshold: float = 0.55,
    limit: int = 50,
) -> list[dict]:
    """Find tenant-scoped duplicate pairs without mutating any data."""
    customers = db.query(Customer).filter(
        Customer.business_id == business_id,
        Customer.status != "merged",
    ).order_by(Customer.created_at.asc(), Customer.id.asc()).limit(1000).all()
    if customer_id is not None:
        target = next((customer for customer in customers if customer.id == customer_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="Customer không tồn tại trong business này.")
        pairs = [(target, other) for other in customers if other.id != target.id]
    else:
        pairs = [
            (customers[index], customers[other_index])
            for index in range(len(customers))
            for other_index in range(index + 1, len(customers))
        ]

    suggestions = []
    for first, second in pairs:
        details = duplicate_evidence(db, first, second)
        if details["confidence_score"] < threshold:
            continue
        if customer_id is not None:
            survivor, source = first, second
        else:
            survivor, source = (first, second) if first.id < second.id else (second, first)
        suggestions.append({
            "survivor_customer_id": survivor.id,
            "source_customer_id": source.id,
            "survivor_name": survivor.name,
            "source_name": source.name,
            "survivor_channel": survivor.channel,
            "source_channel": source.channel,
            **details,
        })
    suggestions.sort(
        key=lambda item: (-item["confidence_score"], item["survivor_customer_id"], item["source_customer_id"])
    )
    return suggestions[:limit]


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
    *,
    allow_merged_source: bool = False,
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
    if source.status == "merged" and not allow_merged_source:
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
) -> list[int]:
    rows = db.query(model).filter(
        model.business_id == business_id,
        model.customer_id == source_id,
    ).all()
    moved_ids = [row.id for row in rows]
    for row in rows:
        row.customer_id = survivor_id
    return moved_ids


def _reassign_identities(
    db: Session,
    business_id: int,
    source_id: int,
    survivor_id: int,
) -> dict:
    identities = db.query(CustomerIdentity).filter(
        CustomerIdentity.business_id == business_id,
        CustomerIdentity.customer_id == source_id,
    ).all()
    moved_ids: list[int] = []
    removed_duplicates: list[dict] = []
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
            removed_duplicates.append({
                "channel": identity.channel,
                "external_account_id": identity.external_account_id,
                "external_user_id": identity.external_user_id,
                "username": identity.username,
                "display_name": identity.display_name,
            })
            db.delete(identity)
        else:
            identity.customer_id = survivor_id
            moved_ids.append(identity.id)
    return {"moved": moved_ids, "removed": removed_duplicates}


def _reassign_tags(
    db: Session,
    business_id: int,
    source_id: int,
    survivor_id: int,
) -> dict:
    links = db.query(CustomerTag).filter(
        CustomerTag.business_id == business_id,
        CustomerTag.customer_id == source_id,
    ).all()
    moved_ids: list[int] = []
    removed_duplicates: list[dict] = []
    for link in links:
        duplicate = db.query(CustomerTag.id).filter(
            CustomerTag.business_id == business_id,
            CustomerTag.customer_id == survivor_id,
            CustomerTag.tag_id == link.tag_id,
            CustomerTag.id != link.id,
        ).first()
        if duplicate is not None:
            removed_duplicates.append({"tag_id": link.tag_id})
            db.delete(link)
        else:
            link.customer_id = survivor_id
            moved_ids.append(link.id)
    return {"moved": moved_ids, "removed": removed_duplicates}


def _reassign_linked_purchase_orders(
    db: Session,
    business_id: int,
    source_id: int,
    survivor_id: int,
) -> list[dict]:
    """Move explicitly customer-linked procurement records during a merge."""
    purchases = db.query(PurchaseOrder).filter(
        PurchaseOrder.business_id == business_id,
    ).all()
    moved: list[dict] = []
    for purchase in purchases:
        metadata = purchase.metadata_
        if not isinstance(metadata, dict) or str(metadata.get("customer_id", "")) != str(source_id):
            continue
        moved.append({"id": purchase.id, "previous_metadata": metadata})
        purchase.metadata_ = {**metadata, "customer_id": survivor_id}
    return moved


def _purchase_order_ids_for_customer(
    db: Session,
    business_id: int,
    customer_id: int,
) -> list[int]:
    return [
        purchase.id
        for purchase in db.query(PurchaseOrder).filter(
            PurchaseOrder.business_id == business_id,
        ).all()
        if isinstance(purchase.metadata_, dict)
        and str(purchase.metadata_.get("customer_id", "")) == str(customer_id)
    ]


def _record_ids_for_customer(
    db: Session,
    model: type,
    business_id: int,
    customer_id: int,
) -> list[int]:
    return [
        row.id
        for row in db.query(model.id).filter(
            model.business_id == business_id,
            model.customer_id == customer_id,
        ).all()
    ]


def _operation_for_merge(db: Session, merge_id: int, business_id: int):
    return db.execute(
        select(customer_merge_operations).where(
            customer_merge_operations.c.customer_merge_id == merge_id,
            customer_merge_operations.c.business_id == business_id,
        )
    ).mappings().first()


def merge_customer(
    db: Session,
    survivor_customer_id: int,
    source_customer_id: int,
    business_id: int,
    reason: str | None = None,
    created_by: int | None = None,
    confidence_score: float | None = None,
    evidence: dict | None = None,
) -> CustomerMerge:
    survivor, source = _customer_pair(
        db, survivor_customer_id, source_customer_id, business_id
    )
    existing_merges = db.query(CustomerMerge.id).filter(
        CustomerMerge.business_id == business_id,
        CustomerMerge.survivor_customer_id == survivor.id,
        CustomerMerge.source_customer_id == source.id,
    ).all()
    for (existing_merge_id,) in existing_merges:
        operation = _operation_for_merge(db, existing_merge_id, business_id)
        # A completed merge is still active. An undone merge remains in the
        # append-only history but must not block a deliberate merge again.
        if operation is None or operation["status"] == "completed":
            raise HTTPException(status_code=409, detail="Hai customer này đã được gộp.")

    before_counts = _counts(db, source)
    track_models = {
        "conversations": Conversation,
        "notes": CustomerNote,
        "facts": CustomerFact,
        "leads": Lead,
        "tickets": Ticket,
        "sales_orders": Order,
    }
    survivor_existing = {
        key: _record_ids_for_customer(db, model, business_id, survivor.id)
        for key, model in track_models.items()
    }
    survivor_existing["identities"] = [
        identity.id
        for identity in db.query(CustomerIdentity.id).filter(
            CustomerIdentity.business_id == business_id,
            CustomerIdentity.customer_id == survivor.id,
        ).all()
    ]
    survivor_existing["tags"] = [
        link.id
        for link in db.query(CustomerTag.id).filter(
            CustomerTag.business_id == business_id,
            CustomerTag.customer_id == survivor.id,
        ).all()
    ]
    survivor_existing["purchase_orders"] = _purchase_order_ids_for_customer(
        db, business_id, survivor.id
    )

    identity_manifest = _reassign_identities(db, business_id, source.id, survivor.id)
    tag_manifest = _reassign_tags(db, business_id, source.id, survivor.id)
    moved_records = {
        "survivor_existing": survivor_existing,
        "moved": {
            "identities": identity_manifest["moved"],
            "tags": tag_manifest["moved"],
            **{
                key: _reassign_rows(db, model, business_id, source.id, survivor.id)
                for key, model in track_models.items()
            },
            "purchase_orders": _reassign_linked_purchase_orders(
                db, business_id, source.id, survivor.id
            ),
        },
        "removed_duplicates": {
            "identities": identity_manifest["removed"],
            "tags": tag_manifest["removed"],
        },
    }

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
    db.flush()
    operation_evidence = evidence or {}
    db.execute(customer_merge_operations.insert().values(
        business_id=business_id,
        customer_merge_id=merge.id,
        status="completed",
        confidence_score=confidence_score,
        evidence=operation_evidence,
        moved_records=moved_records,
        confirmed_at=_utcnow(),
    ))
    db.commit()
    db.refresh(merge)
    return merge


def list_merge_history(
    db: Session,
    customer_id: int,
    business_id: int,
) -> list[dict]:
    merges = db.query(CustomerMerge).filter(
        CustomerMerge.business_id == business_id,
        (CustomerMerge.survivor_customer_id == customer_id)
        | (CustomerMerge.source_customer_id == customer_id),
    ).order_by(CustomerMerge.created_at.desc(), CustomerMerge.id.desc()).all()
    result = []
    for merge in merges:
        operation = _operation_for_merge(db, merge.id, business_id)
        evidence = (operation or {}).get("evidence") or {}
        status = (operation or {}).get("status") or "completed"
        result.append({
            "merge_id": merge.id,
            "business_id": merge.business_id,
            "survivor_customer_id": merge.survivor_customer_id,
            "source_customer_id": merge.source_customer_id,
            "status": status,
            "reason": merge.reason,
            "before_counts": merge.before_counts,
            "after_counts": merge.after_counts,
            "created_at": merge.created_at,
            "confidence_score": (float(operation["confidence_score"]) if operation and operation["confidence_score"] is not None else None),
            "confidence_label": evidence.get("confidence_label"),
            "matched_fields": evidence.get("matched_fields", []),
            "evidence": evidence.get("evidence", []),
            "undone_at": operation.get("undone_at") if operation else None,
            "can_undo": status == "completed",
        })
    return result


def _undo_is_safe(
    db: Session,
    merge: CustomerMerge,
    operation,
) -> tuple[Customer, Customer]:
    survivor, source = _customer_pair(
        db,
        merge.survivor_customer_id,
        merge.source_customer_id,
        merge.business_id,
        allow_merged_source=True,
    )
    if operation is None:
        raise HTTPException(status_code=409, detail="Merge cũ chưa có dữ liệu để hoàn tác an toàn.")
    if operation["status"] != "completed":
        raise HTTPException(status_code=409, detail="Merge này đã được hoàn tác hoặc không còn hiệu lực.")
    if source.status != "merged" or source.merged_into_customer_id != survivor.id:
        raise HTTPException(status_code=409, detail="Trạng thái customer không còn phù hợp để hoàn tác.")

    manifest = operation["moved_records"] or {}
    survivor_existing = manifest.get("survivor_existing", {})
    moved = manifest.get("moved", {})
    models = {
        "conversations": Conversation,
        "notes": CustomerNote,
        "facts": CustomerFact,
        "leads": Lead,
        "tickets": Ticket,
        "sales_orders": Order,
        "identities": CustomerIdentity,
        "tags": CustomerTag,
    }
    for key, model in models.items():
        moved_ids = {int(value) for value in moved.get(key, [])}
        existing_ids = {int(value) for value in survivor_existing.get(key, [])}
        current_survivor_ids = set(_record_ids_for_customer(db, model, merge.business_id, survivor.id))
        expected_ids = existing_ids | moved_ids
        if current_survivor_ids != expected_ids:
            raise HTTPException(
                status_code=409,
                detail="Không thể hoàn tác vì hồ sơ sống đã thay đổi sau lần merge.",
            )
        current_source_ids = set(_record_ids_for_customer(db, model, merge.business_id, source.id))
        if current_source_ids:
            raise HTTPException(
                status_code=409,
                detail="Không thể hoàn tác vì hồ sơ nguồn đã phát sinh dữ liệu mới.",
            )

    moved_purchase_ids = {int(item["id"]) for item in moved.get("purchase_orders", [])}
    existing_purchase_ids = {int(value) for value in survivor_existing.get("purchase_orders", [])}
    current_purchase_ids = set(_purchase_order_ids_for_customer(db, merge.business_id, survivor.id))
    if current_purchase_ids != existing_purchase_ids | moved_purchase_ids:
        raise HTTPException(
            status_code=409,
            detail="Không thể hoàn tác vì đơn nhập liên quan đã thay đổi sau lần merge.",
        )

    for identity_data in (manifest.get("removed_duplicates", {}) or {}).get("identities", []):
        conflict = db.query(CustomerIdentity.id).filter(
            CustomerIdentity.business_id == merge.business_id,
            CustomerIdentity.channel == identity_data["channel"],
            CustomerIdentity.external_account_id == identity_data["external_account_id"],
            CustomerIdentity.external_user_id == identity_data["external_user_id"],
        ).first()
        if conflict is not None:
            raise HTTPException(
                status_code=409,
                detail="Không thể hoàn tác vì định danh kênh đã được dùng lại.",
            )
    return survivor, source


def undo_customer_merge(
    db: Session,
    merge_id: int,
    business_id: int,
    *,
    actor_id: int | None = None,
    reason: str | None = None,
) -> CustomerMerge:
    merge = db.query(CustomerMerge).filter(
        CustomerMerge.id == merge_id,
        CustomerMerge.business_id == business_id,
    ).first()
    if merge is None:
        raise HTTPException(status_code=404, detail="Lịch sử merge không tồn tại trong business này.")
    operation = _operation_for_merge(db, merge_id, business_id)
    survivor, source = _undo_is_safe(db, merge, operation)
    manifest = operation["moved_records"] or {}
    moved = manifest.get("moved", {})
    models = {
        "conversations": Conversation,
        "notes": CustomerNote,
        "facts": CustomerFact,
        "leads": Lead,
        "tickets": Ticket,
        "sales_orders": Order,
        "identities": CustomerIdentity,
        "tags": CustomerTag,
    }
    for key, model in models.items():
        moved_ids = [int(value) for value in moved.get(key, [])]
        if not moved_ids:
            continue
        db.query(model).filter(
            model.id.in_(moved_ids),
            model.business_id == business_id,
            model.customer_id == survivor.id,
        ).update({model.customer_id: source.id}, synchronize_session=False)

    for purchase_info in moved.get("purchase_orders", []):
        purchase = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == int(purchase_info["id"]),
            PurchaseOrder.business_id == business_id,
        ).first()
        if purchase is not None:
            purchase.metadata_ = purchase_info.get("previous_metadata")

    removed = manifest.get("removed_duplicates", {}) or {}
    for identity_data in removed.get("identities", []):
        db.add(CustomerIdentity(
            business_id=business_id,
            customer_id=source.id,
            channel=identity_data["channel"],
            external_account_id=identity_data["external_account_id"],
            external_user_id=identity_data["external_user_id"],
            username=identity_data.get("username"),
            display_name=identity_data.get("display_name"),
        ))
    for tag_data in removed.get("tags", []):
        db.add(CustomerTag(
            business_id=business_id,
            customer_id=source.id,
            tag_id=int(tag_data["tag_id"]),
        ))

    source.status = "active"
    source.merged_into_customer_id = None
    db.execute(update(customer_merge_operations).where(
        customer_merge_operations.c.id == operation["id"],
    ).values(
        status="undone",
        undone_at=_utcnow(),
        undone_by=actor_id,
        undo_reason=reason.strip() if reason and reason.strip() else None,
    ))
    db.commit()
    db.refresh(merge)
    return merge
