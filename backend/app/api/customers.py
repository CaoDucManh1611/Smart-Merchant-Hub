"""Customer 360 and unified timeline endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.customer_360 import customer_segments as customer_segments_table
from app.models.customer_fact import CustomerFact
from app.models.customer_identity import CustomerIdentity
from app.models.customer_note import CustomerNote
from app.models.crm_extended import ConversationTag, CustomerTag, Tag
from app.models.crm_extended import ConversationAssignment
from app.models.message import Message
from app.models.sales import Order
from app.models.purchase_order import PurchaseOrder
from app.models.lead import Lead
from app.models.ticket import Ticket, TicketComment, TicketEvent
from app.models.customer_merge import CustomerMerge
from app.models.audit_log import AuditLog
from app.models.order_event import OrderEvent
from app.models.business_setting import BusinessSetting
from app.schemas.customer import (
    CustomerFactCreate,
    CustomerFactExtractionStatusOut,
    CustomerFactExtractionStatusRequest,
    CustomerFactListOut,
    CustomerFactOut,
    CustomerFactUpdate,
    CustomerConversationOut,
    CustomerIdentityOut,
    CustomerListItem,
    CustomerListOut,
    CustomerNoteCreate,
    CustomerNoteOut,
    CustomerProfileOut,
    CustomerTagCreate,
    CustomerTagListOut,
    CustomerTagOut,
    CustomerTimelineItem,
    CustomerTimelineOut,
)
from app.schemas.customer_merge import (
    CustomerMergeOut,
    CustomerMergePreviewOut,
    CustomerMergeRequest,
    CustomerMergeUndoRequest,
    CustomerSegmentCreate,
    CustomerSegmentOut,
    CustomerSegmentUpdate,
)
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.services.customer_fact_extractor import (
    FACT_EXTRACTION_SETTING_KEY,
    get_customer_fact_extraction_enabled,
)
from app.services.customer_merge_service import (
    duplicate_evidence,
    find_duplicate_suggestions,
    list_merge_history,
    merge_customer,
    preview_merge,
    undo_customer_merge,
)
from app.services.customer_avatar import refresh_customer_avatar_url
from app.auth.dependencies import require_write_access
from app.models.business import User
from app.services.audit_service import record_audit


router = APIRouter()


def _fact_out(fact: CustomerFact) -> CustomerFactOut:
    return CustomerFactOut(
        id=fact.id,
        business_id=fact.business_id,
        customer_id=fact.customer_id,
        fact_type=fact.fact_type,
        fact_key=fact.fact_key,
        fact_value=fact.fact_value_json,
        confidence=fact.confidence,
        source_type=fact.source_type,
        source_message_id=fact.source_message_id,
        source_order_id=fact.source_order_id,
        observed_at=fact.observed_at,
        valid_from=fact.valid_from,
        valid_until=fact.valid_until,
        extractor=fact.extractor,
        extractor_version=fact.extractor_version,
        is_verified=fact.is_verified,
        created_at=fact.created_at,
        updated_at=fact.updated_at,
    )


def _validate_fact_sources(
    db: Session,
    customer: Customer,
    tenant: TenantContext,
    source_message_id: int | None,
    source_order_id: int | None,
) -> None:
    if source_message_id is not None and source_order_id is not None:
        raise HTTPException(
            status_code=422,
            detail="Một fact chỉ được liên kết với message hoặc order, không phải cả hai.",
        )
    if source_message_id is not None:
        exists = db.query(Message.id).join(
            Conversation, Conversation.id == Message.conversation_id
        ).filter(
            Message.id == source_message_id,
            Conversation.business_id == tenant.business_id,
            Conversation.customer_id == customer.id,
        ).first()
        if exists is None:
            raise HTTPException(status_code=422, detail="Message nguồn không thuộc customer/business này.")
    if source_order_id is not None:
        exists = db.query(Order.id).filter(
            Order.id == source_order_id,
            Order.business_id == tenant.business_id,
            Order.customer_id == customer.id,
        ).first()
        if exists is None:
            raise HTTPException(status_code=422, detail="Order nguồn không thuộc customer/business này.")


def _get_customer(db: Session, customer_id: int, tenant: TenantContext) -> Customer:
    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.business_id == tenant.business_id,
    ).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer không tồn tại.")
    return customer


def _segment_row_to_dict(db: Session, row) -> dict:
    data = dict(row._mapping if hasattr(row, "_mapping") else row)
    tag_ids = [int(value) for value in (data.get("tag_ids") or [])]
    customer_query = db.query(Customer.id).filter(
        Customer.business_id == data["business_id"],
        Customer.status != "merged",
    )
    if data.get("match_mode") == "all":
        for tag_id in tag_ids:
            customer_query = customer_query.filter(Customer.id.in_(
                db.query(CustomerTag.customer_id).filter(
                    CustomerTag.business_id == data["business_id"],
                    CustomerTag.tag_id == tag_id,
                )
            ))
    elif tag_ids:
        customer_query = customer_query.join(
            CustomerTag,
            CustomerTag.customer_id == Customer.id,
        ).filter(
            CustomerTag.business_id == data["business_id"],
            CustomerTag.tag_id.in_(tag_ids),
        ).distinct()
    data["tag_ids"] = tag_ids
    data["customer_count"] = customer_query.count()
    return data


def _get_segment(db: Session, segment_id: int, tenant: TenantContext) -> dict:
    row = db.execute(select(customer_segments_table).where(
        customer_segments_table.c.id == segment_id,
        customer_segments_table.c.business_id == tenant.business_id,
    )).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Segment không tồn tại trong business này.")
    return _segment_row_to_dict(db, row)


def _validate_segment_tags(db: Session, tenant: TenantContext, tag_ids: list[int]) -> list[int]:
    normalized = list(dict.fromkeys(int(value) for value in tag_ids))
    if not normalized or any(value <= 0 for value in normalized):
        raise HTTPException(status_code=422, detail="Segment phải có ít nhất một tag hợp lệ.")
    found = {
        tag_id
        for (tag_id,) in db.query(Tag.id).filter(
            Tag.business_id == tenant.business_id,
            Tag.id.in_(normalized),
        ).all()
    }
    missing = [tag_id for tag_id in normalized if tag_id not in found]
    if missing:
        raise HTTPException(status_code=422, detail="Segment chỉ được dùng tag thuộc business hiện tại.")
    return normalized


def _segment_customer_query(db: Session, segment: dict):
    query = db.query(Customer).filter(
        Customer.business_id == segment["business_id"],
        Customer.status != "merged",
    )
    tag_ids = segment.get("tag_ids") or []
    if segment.get("match_mode") == "all":
        for tag_id in tag_ids:
            query = query.filter(Customer.id.in_(
                db.query(CustomerTag.customer_id).filter(
                    CustomerTag.business_id == segment["business_id"],
                    CustomerTag.tag_id == tag_id,
                )
            ))
    elif tag_ids:
        query = query.join(CustomerTag, CustomerTag.customer_id == Customer.id).filter(
            CustomerTag.business_id == segment["business_id"],
            CustomerTag.tag_id.in_(tag_ids),
        ).distinct()
    return query


def _customer_list_out(db: Session, query, *, offset: int = 0, limit: int = 200) -> CustomerListOut:
    total = query.count()
    customers = query.order_by(Customer.updated_at.desc(), Customer.id.desc()).offset(offset).limit(limit).all()
    items = []
    for customer in customers:
        count = db.query(func.count(Conversation.id)).filter(
            Conversation.business_id == customer.business_id,
            Conversation.customer_id == customer.id,
        ).scalar() or 0
        items.append(CustomerListItem(
            id=customer.id,
            name=customer.name,
            email=customer.email,
            phone=customer.phone,
            channel=customer.channel,
            updated_at=customer.updated_at,
            conversation_count=count,
        ))
    return CustomerListOut(items=items, total=total)


@router.get("/duplicates", response_model=dict)
def list_duplicate_suggestions(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    customer_id: int | None = Query(default=None, ge=1),
    threshold: float = Query(default=0.55, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=200),
):
    items = find_duplicate_suggestions(
        db,
        tenant.business_id,
        customer_id=customer_id,
        threshold=threshold,
        limit=limit,
    )
    return {"items": items, "total": len(items)}


@router.get("/segments", response_model=dict)
def list_customer_segments(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    rows = db.execute(select(customer_segments_table).where(
        customer_segments_table.c.business_id == tenant.business_id,
    ).order_by(customer_segments_table.c.name.asc())).all()
    items = [CustomerSegmentOut(**_segment_row_to_dict(db, row)) for row in rows]
    return {"items": items, "total": len(items)}


@router.post("/segments", response_model=CustomerSegmentOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_customer_segment(
    payload: CustomerSegmentCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    tag_ids = _validate_segment_tags(db, tenant, payload.tag_ids)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Tên segment không được rỗng.")
    existing = db.execute(select(customer_segments_table.c.id).where(
        customer_segments_table.c.business_id == tenant.business_id,
        customer_segments_table.c.name == name,
    )).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Tên segment đã tồn tại trong business này.")
    result = db.execute(customer_segments_table.insert().values(
        business_id=tenant.business_id,
        name=name,
        description=payload.description.strip() if payload.description else None,
        tag_ids=tag_ids,
        match_mode=payload.match_mode,
        created_by=actor.id if actor else None,
    ))
    segment_id = int(result.inserted_primary_key[0])
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="segment_create",
        resource_type="customer_segment",
        resource_id=segment_id,
        metadata={"name": name, "tag_ids": tag_ids, "match_mode": payload.match_mode},
    )
    db.commit()
    segment = _get_segment(db, segment_id, tenant)
    return CustomerSegmentOut(**segment)


@router.patch("/segments/{segment_id}", response_model=CustomerSegmentOut, dependencies=[Depends(require_write_access)])
def update_customer_segment(
    segment_id: int,
    payload: CustomerSegmentUpdate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    current = _get_segment(db, segment_id, tenant)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise HTTPException(status_code=422, detail="Tên segment không được rỗng.")
        duplicate = db.execute(select(customer_segments_table.c.id).where(
            customer_segments_table.c.business_id == tenant.business_id,
            customer_segments_table.c.name == data["name"],
            customer_segments_table.c.id != segment_id,
        )).first()
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Tên segment đã tồn tại trong business này.")
    if "tag_ids" in data:
        data["tag_ids"] = _validate_segment_tags(db, tenant, data["tag_ids"])
    if "description" in data and data["description"] is not None:
        data["description"] = data["description"].strip() or None
    if not data:
        return CustomerSegmentOut(**current)
    data["updated_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
    db.execute(update(customer_segments_table).where(
        customer_segments_table.c.id == segment_id,
        customer_segments_table.c.business_id == tenant.business_id,
    ).values(**data))
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="segment_update",
        resource_type="customer_segment",
        resource_id=segment_id,
        metadata={"fields": sorted(key for key in data if key != "updated_at")},
    )
    db.commit()
    return CustomerSegmentOut(**_get_segment(db, segment_id, tenant))


@router.delete("/segments/{segment_id}", status_code=204, dependencies=[Depends(require_write_access)])
def delete_customer_segment(
    segment_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    _get_segment(db, segment_id, tenant)
    db.execute(delete(customer_segments_table).where(
        customer_segments_table.c.id == segment_id,
        customer_segments_table.c.business_id == tenant.business_id,
    ))
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="segment_delete",
        resource_type="customer_segment",
        resource_id=segment_id,
        metadata={},
    )
    db.commit()
    return Response(status_code=204)


@router.get("/segments/{segment_id}/customers", response_model=CustomerListOut)
def list_segment_customers(
    segment_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    segment = _get_segment(db, segment_id, tenant)
    return _customer_list_out(
        db,
        _segment_customer_query(db, segment),
        offset=offset,
        limit=limit,
    )


@router.get("", response_model=CustomerListOut)
def list_customers(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tag: str | None = Query(default=None, min_length=1, max_length=80),
    tag_ids: str | None = Query(default=None, max_length=500),
    match_mode: str = Query(default="all", pattern="^(all|any)$"),
):
    base = db.query(Customer).filter(
        Customer.business_id == tenant.business_id,
        Customer.status != "merged",
    )
    if tag:
        base = base.join(CustomerTag, CustomerTag.customer_id == Customer.id).join(
            Tag, Tag.id == CustomerTag.tag_id
        ).filter(
            CustomerTag.business_id == tenant.business_id,
            Tag.business_id == tenant.business_id,
            Tag.name == tag.strip(),
        ).distinct()
    if tag_ids:
        try:
            requested_tag_ids = [int(value.strip()) for value in tag_ids.split(",") if value.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="tag_ids phải là danh sách số nguyên.") from exc
        if any(tag_id <= 0 for tag_id in requested_tag_ids):
            raise HTTPException(status_code=422, detail="tag_ids phải là số nguyên dương.")
        normalized_tag_ids = list(dict.fromkeys(requested_tag_ids))
        if match_mode == "all":
            for tag_id in normalized_tag_ids:
                customer_ids = db.query(CustomerTag.customer_id).filter(
                    CustomerTag.business_id == tenant.business_id,
                    CustomerTag.tag_id == tag_id,
                )
                base = base.filter(Customer.id.in_(customer_ids))
        else:
            customer_ids = db.query(CustomerTag.customer_id).filter(
                CustomerTag.business_id == tenant.business_id,
                CustomerTag.tag_id.in_(normalized_tag_ids),
            )
            base = base.filter(Customer.id.in_(customer_ids))
    total = base.count()
    customers = base.order_by(Customer.updated_at.desc(), Customer.id.desc()).offset(offset).limit(limit).all()
    items = []
    for customer in customers:
        count = db.query(func.count(Conversation.id)).filter(
            Conversation.business_id == tenant.business_id,
            Conversation.customer_id == customer.id,
        ).scalar() or 0
        items.append(CustomerListItem(
            id=customer.id,
            name=customer.name,
            email=customer.email,
            phone=customer.phone,
            channel=customer.channel,
            updated_at=customer.updated_at,
            conversation_count=count,
        ))
    return CustomerListOut(items=items, total=total)


@router.post("/{customer_id}/merge-preview", response_model=CustomerMergePreviewOut, dependencies=[Depends(require_write_access)])
def customer_merge_preview(
    customer_id: int,
    payload: CustomerMergeRequest,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Preview how many tenant-owned records would move to the survivor."""
    survivor, source, survivor_counts, source_counts = preview_merge(
        db,
        survivor_customer_id=customer_id,
        source_customer_id=payload.source_customer_id,
        business_id=tenant.business_id,
    )
    details = duplicate_evidence(db, survivor, source)
    return CustomerMergePreviewOut(
        survivor_customer_id=survivor.id,
        source_customer_id=source.id,
        survivor_counts=survivor_counts,
        source_counts=source_counts,
        **details,
        can_merge=True,
    )


@router.post("/{customer_id}/merge", response_model=CustomerMergeOut, dependencies=[Depends(require_write_access)])
def customer_merge(
    customer_id: int,
    payload: CustomerMergeRequest,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    """Merge a duplicate customer while retaining an append-only merge record."""
    if not payload.confirm:
        raise HTTPException(
            status_code=409,
            detail="Cần xác nhận merge sau khi đã xem preview và điểm tin cậy.",
        )
    survivor, source, _survivor_counts, _source_counts = preview_merge(
        db,
        survivor_customer_id=customer_id,
        source_customer_id=payload.source_customer_id,
        business_id=tenant.business_id,
    )
    evidence = duplicate_evidence(db, survivor, source)
    merge = merge_customer(
        db,
        survivor_customer_id=customer_id,
        source_customer_id=payload.source_customer_id,
        business_id=tenant.business_id,
        reason=payload.reason,
        created_by=actor.id if actor else None,
        confidence_score=evidence["confidence_score"],
        evidence=evidence,
    )
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="merge",
        resource_type="customer",
        resource_id=str(customer_id),
        metadata={"source_customer_id": payload.source_customer_id, "reason": payload.reason},
    )
    db.commit()
    return CustomerMergeOut(
        merge_id=merge.id,
        business_id=merge.business_id,
        survivor_customer_id=merge.survivor_customer_id,
        source_customer_id=merge.source_customer_id,
        status="completed",
        reason=merge.reason,
        before_counts=merge.before_counts,
        after_counts=merge.after_counts,
        created_at=merge.created_at,
        confidence_score=evidence["confidence_score"],
        confidence_label=evidence["confidence_label"],
        matched_fields=evidence["matched_fields"],
        evidence=evidence["evidence"],
        can_undo=True,
    )


@router.get("/{customer_id}/merge-history", response_model=dict)
def customer_merge_history(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    _get_customer(db, customer_id, tenant)
    items = list_merge_history(db, customer_id, tenant.business_id)
    return {"items": items, "total": len(items)}


@router.post("/{customer_id}/merge-history/{merge_id}/undo", response_model=CustomerMergeOut, dependencies=[Depends(require_write_access)])
def undo_customer_merge_endpoint(
    customer_id: int,
    merge_id: int,
    payload: CustomerMergeUndoRequest,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    merge = db.query(CustomerMerge).filter(
        CustomerMerge.id == merge_id,
        CustomerMerge.business_id == tenant.business_id,
        (CustomerMerge.survivor_customer_id == customer_id)
        | (CustomerMerge.source_customer_id == customer_id),
    ).first()
    if merge is None:
        raise HTTPException(status_code=404, detail="Merge không thuộc customer/business này.")
    undo_customer_merge(
        db,
        merge_id,
        tenant.business_id,
        actor_id=actor.id if actor else None,
        reason=payload.reason,
    )
    operation_items = list_merge_history(db, customer_id, tenant.business_id)
    history = next(item for item in operation_items if item["merge_id"] == merge_id)
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="merge_undo",
        resource_type="customer",
        resource_id=str(customer_id),
        metadata={"merge_id": merge_id, "reason": payload.reason},
    )
    db.commit()
    return CustomerMergeOut(**history)


@router.get("/fact-extraction-status", response_model=CustomerFactExtractionStatusOut)
def get_fact_extraction_status(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return CustomerFactExtractionStatusOut(
        enabled=get_customer_fact_extraction_enabled(db, tenant.business_id),
    )


@router.post("/fact-extraction-status", response_model=CustomerFactExtractionStatusOut, dependencies=[Depends(require_write_access)])
def set_fact_extraction_status(
    payload: CustomerFactExtractionStatusRequest,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    setting = db.query(BusinessSetting).filter(
        BusinessSetting.business_id == tenant.business_id,
        BusinessSetting.key == FACT_EXTRACTION_SETTING_KEY,
    ).first()
    value = "true" if payload.enabled else "false"
    if setting is None:
        setting = BusinessSetting(
            business_id=tenant.business_id,
            key=FACT_EXTRACTION_SETTING_KEY,
            value=value,
        )
        db.add(setting)
    else:
        setting.value = value
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="fact_extraction_setting_update",
        resource_type="business_setting",
        resource_id=FACT_EXTRACTION_SETTING_KEY,
        metadata={"enabled": payload.enabled},
    )
    db.commit()
    return CustomerFactExtractionStatusOut(enabled=payload.enabled)


@router.get("/tags/catalog")
def list_customer_tag_catalog(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """List tags used by this tenant for segmentation controls."""
    rows = db.query(Tag).filter(Tag.business_id == tenant.business_id).order_by(Tag.name.asc()).all()
    count_rows = db.query(
        CustomerTag.tag_id,
        func.count(func.distinct(CustomerTag.customer_id)),
    ).join(
        Customer,
        Customer.id == CustomerTag.customer_id,
    ).filter(
        CustomerTag.business_id == tenant.business_id,
        Customer.business_id == tenant.business_id,
        Customer.status != "merged",
    ).group_by(CustomerTag.tag_id).all()
    customer_counts = {int(tag_id): int(count) for tag_id, count in count_rows}
    return {
        "items": [
            {
                "id": tag.id,
                "name": tag.name,
                "color": tag.color,
                "customer_count": customer_counts.get(tag.id, 0),
            }
            for tag in rows
        ],
        "total": len(rows),
    }


@router.get("/{customer_id}", response_model=CustomerProfileOut)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    customer = _get_customer(db, customer_id, tenant)
    identities = db.query(CustomerIdentity).filter(
        CustomerIdentity.business_id == tenant.business_id,
        CustomerIdentity.customer_id == customer.id,
    ).order_by(CustomerIdentity.last_seen_at.desc()).all()
    conversations = db.query(Conversation).filter(
        Conversation.business_id == tenant.business_id,
        Conversation.customer_id == customer.id,
    ).order_by(Conversation.updated_at.desc(), Conversation.id.desc()).all()
    conversation_tags = db.query(Tag.name).join(
        ConversationTag, ConversationTag.tag_id == Tag.id
    ).join(
        Conversation, Conversation.id == ConversationTag.conversation_id
    ).filter(
        Tag.business_id == tenant.business_id,
        Conversation.business_id == tenant.business_id,
        Conversation.customer_id == customer.id,
    ).distinct().order_by(Tag.name.asc()).all()
    customer_tags = db.query(Tag.name).join(
        CustomerTag, CustomerTag.tag_id == Tag.id
    ).filter(
        CustomerTag.business_id == tenant.business_id,
        CustomerTag.customer_id == customer.id,
        Tag.business_id == tenant.business_id,
    ).distinct().order_by(Tag.name.asc()).all()
    facts = db.query(CustomerFact).filter(
        CustomerFact.business_id == tenant.business_id,
        CustomerFact.customer_id == customer.id,
    ).order_by(CustomerFact.is_verified.desc(), CustomerFact.updated_at.desc(), CustomerFact.id.desc()).all()
    tag_names = sorted({name for (name,) in conversation_tags + customer_tags})
    return CustomerProfileOut(
        id=customer.id,
        business_id=customer.business_id,
        name=customer.name,
        email=customer.email,
        phone=customer.phone,
        address=customer.address,
        avatar_url=refresh_customer_avatar_url(
            customer.avatar_url,
            customer_id=customer.id,
            business_id=tenant.business_id,
        ),
        created_at=customer.created_at,
        updated_at=customer.updated_at,
        identities=[CustomerIdentityOut.model_validate(identity) for identity in identities],
        conversations=[CustomerConversationOut.model_validate(conversation) for conversation in conversations],
        tags=tag_names,
        facts=[_fact_out(fact) for fact in facts],
        conversation_count=len(conversations),
    )


@router.get("/{customer_id}/facts", response_model=CustomerFactListOut)
def list_customer_facts(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    fact_type: str | None = Query(default=None, min_length=1, max_length=50),
    verified: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List tenant-owned facts for one canonical customer profile."""
    _get_customer(db, customer_id, tenant)
    query = db.query(CustomerFact).filter(
        CustomerFact.business_id == tenant.business_id,
        CustomerFact.customer_id == customer_id,
    )
    if fact_type:
        query = query.filter(CustomerFact.fact_type == fact_type.strip())
    if verified is not None:
        query = query.filter(CustomerFact.is_verified == verified)
    total = query.count()
    facts = query.order_by(
        CustomerFact.is_verified.desc(),
        CustomerFact.updated_at.desc(),
        CustomerFact.id.desc(),
    ).offset(offset).limit(limit).all()
    return CustomerFactListOut(items=[_fact_out(fact) for fact in facts], total=total)


@router.post("/{customer_id}/facts", response_model=CustomerFactOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_customer_fact(
    customer_id: int,
    payload: CustomerFactCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    """Create an explicit or extracted fact without crossing tenants."""
    customer = _get_customer(db, customer_id, tenant)
    fact_type = payload.fact_type.strip()
    fact_key = payload.fact_key.strip()
    source_type = payload.source_type.strip().lower()
    if not fact_type or not fact_key or not source_type:
        raise HTTPException(status_code=422, detail="fact_type, fact_key và source_type không được rỗng.")
    _validate_fact_sources(
        db,
        customer,
        tenant,
        payload.source_message_id,
        payload.source_order_id,
    )
    fact = CustomerFact(
        business_id=tenant.business_id,
        customer_id=customer.id,
        fact_type=fact_type,
        fact_key=fact_key,
        fact_value_json=payload.fact_value,
        confidence=payload.confidence,
        source_type=source_type,
        source_message_id=payload.source_message_id,
        source_order_id=payload.source_order_id,
        observed_at=payload.observed_at or datetime.now(timezone.utc).replace(tzinfo=None),
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        extractor=payload.extractor,
        extractor_version=payload.extractor_version,
        is_verified=payload.is_verified,
    )
    db.add(fact)
    db.flush()
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="fact_create",
        resource_type="customer_fact",
        resource_id=fact.id,
        metadata={
            "customer_id": customer.id,
            "fact_type": fact.fact_type,
            "fact_key": fact.fact_key,
            "source_type": fact.source_type,
            "source_message_id": fact.source_message_id,
            "source_order_id": fact.source_order_id,
        },
    )
    db.commit()
    db.refresh(fact)
    return _fact_out(fact)


def _get_customer_fact(
    db: Session,
    customer_id: int,
    fact_id: int,
    tenant: TenantContext,
) -> CustomerFact:
    fact = db.query(CustomerFact).filter(
        CustomerFact.id == fact_id,
        CustomerFact.business_id == tenant.business_id,
        CustomerFact.customer_id == customer_id,
    ).first()
    if fact is None:
        raise HTTPException(status_code=404, detail="Customer fact không tồn tại.")
    return fact


@router.patch("/{customer_id}/facts/{fact_id}", response_model=CustomerFactOut, dependencies=[Depends(require_write_access)])
def update_customer_fact(
    customer_id: int,
    fact_id: int,
    payload: CustomerFactUpdate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    fact = _get_customer_fact(db, customer_id, fact_id, tenant)
    data = payload.model_dump(exclude_unset=True)
    source_message_id = data.get("source_message_id", fact.source_message_id)
    source_order_id = data.get("source_order_id", fact.source_order_id)
    customer = _get_customer(db, customer_id, tenant)
    _validate_fact_sources(db, customer, tenant, source_message_id, source_order_id)

    for key in ("fact_type", "fact_key", "source_type"):
        if key in data:
            value = str(data[key]).strip()
            if not value:
                raise HTTPException(status_code=422, detail=f"{key} không được rỗng.")
            data[key] = value.lower() if key == "source_type" else value
    if "fact_value" in data:
        fact.fact_value_json = data.pop("fact_value")
    for key, value in data.items():
        setattr(fact, key, value)
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="fact_update",
        resource_type="customer_fact",
        resource_id=fact.id,
        metadata={"customer_id": customer_id, "fields": sorted(data.keys())},
    )
    db.commit()
    db.refresh(fact)
    return _fact_out(fact)


@router.delete("/{customer_id}/facts/{fact_id}", status_code=204, dependencies=[Depends(require_write_access)])
def delete_customer_fact(
    customer_id: int,
    fact_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    fact = _get_customer_fact(db, customer_id, fact_id, tenant)
    db.delete(fact)
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="fact_delete",
        resource_type="customer_fact",
        resource_id=fact.id,
        metadata={"customer_id": customer_id, "fact_type": fact.fact_type, "fact_key": fact.fact_key},
    )
    db.commit()
    return Response(status_code=204)


@router.get("/{customer_id}/tags", response_model=CustomerTagListOut)
def list_customer_tags(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    customer = _get_customer(db, customer_id, tenant)
    rows = db.query(Tag).join(
        CustomerTag, CustomerTag.tag_id == Tag.id
    ).filter(
        CustomerTag.business_id == tenant.business_id,
        CustomerTag.customer_id == customer.id,
        Tag.business_id == tenant.business_id,
    ).order_by(Tag.name.asc()).all()
    return CustomerTagListOut(
        items=[CustomerTagOut(id=tag.id, name=tag.name, color=tag.color) for tag in rows],
        total=len(rows),
    )


@router.post("/{customer_id}/tags", response_model=CustomerTagOut, status_code=201, dependencies=[Depends(require_write_access)])
def add_customer_tag(
    customer_id: int,
    payload: CustomerTagCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    customer = _get_customer(db, customer_id, tenant)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Tên tag không được rỗng.")
    tag = db.query(Tag).filter(
        Tag.business_id == tenant.business_id,
        Tag.name == name,
    ).first()
    if tag is None:
        tag = Tag(business_id=tenant.business_id, name=name, color=payload.color)
        db.add(tag)
        db.flush()
    elif payload.color and tag.color != payload.color:
        tag.color = payload.color
    link = db.query(CustomerTag).filter(
        CustomerTag.business_id == tenant.business_id,
        CustomerTag.customer_id == customer.id,
        CustomerTag.tag_id == tag.id,
    ).first()
    changed = link is None
    if changed:
        db.add(CustomerTag(
            business_id=tenant.business_id,
            customer_id=customer.id,
            tag_id=tag.id,
        ))
    if changed:
        record_audit(
            db,
            business_id=tenant.business_id,
            user_id=actor.id if actor else None,
            action="tag_add",
            resource_type="customer",
            resource_id=str(customer.id),
            metadata={"tag_id": tag.id, "tag": tag.name},
        )
    db.commit()
    db.refresh(tag)
    return CustomerTagOut(id=tag.id, name=tag.name, color=tag.color)


@router.delete("/{customer_id}/tags/{tag_id}", status_code=204, dependencies=[Depends(require_write_access)])
def remove_customer_tag(
    customer_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    customer = _get_customer(db, customer_id, tenant)
    link = db.query(CustomerTag).filter(
        CustomerTag.business_id == tenant.business_id,
        CustomerTag.customer_id == customer.id,
        CustomerTag.tag_id == tag_id,
    ).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Tag không được gắn cho customer.")
    tag = db.query(Tag).filter(Tag.id == tag_id, Tag.business_id == tenant.business_id).first()
    db.delete(link)
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="tag_remove",
        resource_type="customer",
        resource_id=str(customer.id),
        metadata={"tag_id": tag_id, "tag": tag.name if tag else None},
    )
    db.commit()
    return Response(status_code=204)


@router.get("/{customer_id}/identities", response_model=list[CustomerIdentityOut])
def list_customer_identities(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    _get_customer(db, customer_id, tenant)
    identities = db.query(CustomerIdentity).filter(
        CustomerIdentity.business_id == tenant.business_id,
        CustomerIdentity.customer_id == customer_id,
    ).order_by(CustomerIdentity.last_seen_at.desc()).all()
    return [CustomerIdentityOut.model_validate(identity) for identity in identities]


@router.get("/{customer_id}/timeline", response_model=CustomerTimelineOut)
def customer_timeline(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    _get_customer(db, customer_id, tenant)
    identities = db.query(CustomerIdentity).filter(
        CustomerIdentity.business_id == tenant.business_id,
        CustomerIdentity.customer_id == customer_id,
    ).all()
    facts = db.query(CustomerFact).filter(
        CustomerFact.business_id == tenant.business_id,
        CustomerFact.customer_id == customer_id,
    ).all()
    messages = db.query(Message).join(
        Conversation, Conversation.id == Message.conversation_id
    ).filter(
        Conversation.business_id == tenant.business_id,
        Conversation.customer_id == customer_id,
    ).all()
    notes = db.query(CustomerNote).filter(
        CustomerNote.business_id == tenant.business_id,
        CustomerNote.customer_id == customer_id,
    ).all()
    leads = db.query(Lead).filter(
        Lead.business_id == tenant.business_id,
        Lead.customer_id == customer_id,
    ).all()
    orders = db.query(Order).filter(
        Order.business_id == tenant.business_id,
        Order.customer_id == customer_id,
    ).all()
    order_ids = [order.id for order in orders]
    order_events = db.query(OrderEvent).filter(
        OrderEvent.business_id == tenant.business_id,
        OrderEvent.order_type == "sales_order",
        OrderEvent.order_id.in_(order_ids),
    ).all() if order_ids else []
    # Purchase Orders are shop-level records.  Include one in a customer's
    # timeline only when the operator explicitly linked it through metadata
    # (``{"customer_id": ...}``), avoiding unrelated supplier activity on
    # every customer profile.
    purchase_orders = [
        purchase for purchase in db.query(PurchaseOrder).filter(
            PurchaseOrder.business_id == tenant.business_id,
        ).all()
        if isinstance(purchase.metadata_, dict)
        and str(purchase.metadata_.get("customer_id", "")) == str(customer_id)
    ]
    tickets = db.query(Ticket).filter(
        Ticket.business_id == tenant.business_id,
        Ticket.customer_id == customer_id,
    ).all()
    ticket_ids = [ticket.id for ticket in tickets]
    ticket_events = db.query(TicketEvent).filter(
        TicketEvent.business_id == tenant.business_id,
        TicketEvent.ticket_id.in_(ticket_ids),
    ).all() if ticket_ids else []
    comments = db.query(TicketComment).filter(
        TicketComment.business_id == tenant.business_id,
        TicketComment.ticket_id.in_(ticket_ids),
    ).all() if ticket_ids else []
    assignments = db.query(ConversationAssignment).join(
        Conversation, Conversation.id == ConversationAssignment.conversation_id
    ).filter(
        Conversation.business_id == tenant.business_id,
        Conversation.customer_id == customer_id,
    ).all()
    merges = db.query(CustomerMerge).filter(
        CustomerMerge.business_id == tenant.business_id,
        (CustomerMerge.survivor_customer_id == customer_id)
        | (CustomerMerge.source_customer_id == customer_id),
    ).all()
    profile_history = db.query(AuditLog).filter(
        AuditLog.business_id == tenant.business_id,
        AuditLog.resource_type == "customer",
        AuditLog.resource_id == str(customer_id),
        AuditLog.action.in_(("profile_created", "profile_update")),
    ).all()
    tag_history = db.query(AuditLog).filter(
        AuditLog.business_id == tenant.business_id,
        AuditLog.resource_type == "customer",
        AuditLog.resource_id == str(customer_id),
        AuditLog.action.in_(("tag_add", "tag_remove")),
    ).all()
    merge_undo_history = db.query(AuditLog).filter(
        AuditLog.business_id == tenant.business_id,
        AuditLog.resource_type == "customer",
        AuditLog.resource_id == str(customer_id),
        AuditLog.action == "merge_undo",
    ).all()
    items = [CustomerTimelineItem(
        event_type="message",
        event_id=message.id,
        occurred_at=message.sent_at or message.received_at,
        channel=message.channel,
        direction=message.direction,
        content=message.content,
        conversation_id=message.conversation_id,
        created_by=message.sender_user_id,
    ) for message in messages]
    items.extend(CustomerTimelineItem(
        event_type="identity",
        event_id=identity.id,
        occurred_at=identity.last_seen_at or identity.created_at,
        channel=identity.channel,
        content=identity.display_name or identity.username or identity.external_user_id,
        created_by=None,
        metadata={
            "identity_id": identity.id,
            "external_account_id": identity.external_account_id,
            "external_user_id": identity.external_user_id,
            "username": identity.username,
            "display_name": identity.display_name,
        },
    ) for identity in identities)
    items.extend(CustomerTimelineItem(
        event_type="fact",
        event_id=fact.id,
        occurred_at=fact.updated_at or fact.observed_at or fact.created_at,
        content=fact.fact_key,
        created_by=None,
        metadata={
            "fact_type": fact.fact_type,
            "fact_key": fact.fact_key,
            "fact_value": fact.fact_value_json,
            "confidence": fact.confidence,
            "source_type": fact.source_type,
            "source_message_id": fact.source_message_id,
            "source_order_id": fact.source_order_id,
            "is_verified": fact.is_verified,
        },
    ) for fact in facts)
    items.extend(CustomerTimelineItem(
        event_type="note",
        event_id=note.id,
        occurred_at=note.created_at,
        content=note.content,
        created_by=note.created_by,
    ) for note in notes)
    items.extend(CustomerTimelineItem(
        event_type="lead",
        event_id=lead.id,
        occurred_at=lead.updated_at or lead.created_at,
        channel=lead.source_channel,
        content=lead.title,
        conversation_id=lead.conversation_id,
        created_by=lead.assigned_user_id,
        metadata={"stage": lead.stage, "status": lead.status, "value": str(lead.value)},
    ) for lead in leads)
    items.extend(CustomerTimelineItem(
        event_type="sales_order",
        event_id=order.id,
        occurred_at=order.updated_at or order.created_at,
        content=order.order_number,
        conversation_id=order.conversation_id,
        metadata={"status": order.status, "total_amount": str(order.total_amount)},
    ) for order in orders)
    order_by_id = {order.id: order for order in orders}
    items.extend(CustomerTimelineItem(
        event_type="order_payment" if event.event_type in {"payment_created", "refund_created"} else "sales_order",
        event_id=event.id,
        occurred_at=event.created_at,
        channel=(order_by_id.get(event.order_id).conversation.channel if order_by_id.get(event.order_id) and order_by_id.get(event.order_id).conversation else None),
        content=(
            "Hoàn tiền đơn hàng" if event.event_type == "refund_created"
            else "Thanh toán đơn hàng" if event.event_type == "payment_created"
            else f"Cập nhật đơn {order_by_id.get(event.order_id).order_number if order_by_id.get(event.order_id) else event.order_id}"
        ),
        conversation_id=order_by_id.get(event.order_id).conversation_id if order_by_id.get(event.order_id) else None,
        created_by=event.actor_id,
        metadata={"event_subtype": event.event_type, "from_status": event.from_status, "to_status": event.to_status, **(event.metadata_ or {})},
    ) for event in order_events)
    items.extend(CustomerTimelineItem(
        event_type="purchase_order",
        event_id=purchase.id,
        occurred_at=purchase.updated_at or purchase.created_at,
        content=purchase.po_number,
        metadata={"status": purchase.status, "supplier_name": purchase.supplier_name, "total_spend": str(purchase.total_spend)},
    ) for purchase in purchase_orders)
    items.extend(CustomerTimelineItem(
        event_type="ticket",
        event_id=ticket.id,
        occurred_at=ticket.updated_at or ticket.created_at,
        content=ticket.title,
        conversation_id=ticket.conversation_id,
        created_by=ticket.assigned_user_id,
        metadata={"status": ticket.status, "priority": ticket.priority},
    ) for ticket in tickets)
    items.extend(CustomerTimelineItem(
        event_type="ticket_comment",
        event_id=comment.id,
        occurred_at=comment.created_at,
        content=comment.body,
        created_by=comment.author_user_id,
        metadata={"ticket_id": comment.ticket_id},
    ) for comment in comments)
    ticket_by_id = {ticket.id: ticket for ticket in tickets}
    items.extend(CustomerTimelineItem(
        event_type="ticket_event",
        event_id=event.id,
        occurred_at=event.created_at,
        content=event.event_type,
        conversation_id=ticket_by_id.get(event.ticket_id).conversation_id if ticket_by_id.get(event.ticket_id) else None,
        created_by=event.actor_user_id,
        metadata={
            "ticket_id": event.ticket_id,
            "event_subtype": event.event_type,
            "from_value": event.from_value,
            "to_value": event.to_value,
        },
    ) for event in ticket_events)
    items.extend(CustomerTimelineItem(
        event_type="assignment",
        event_id=assignment.id,
        occurred_at=assignment.assigned_at,
        content="Phân công hội thoại",
        conversation_id=assignment.conversation_id,
        created_by=assignment.assigned_by,
        metadata={"user_id": assignment.user_id, "assignment_type": assignment.assignment_type},
    ) for assignment in assignments)
    items.extend(CustomerTimelineItem(
        event_type="customer_merge",
        event_id=merge.id,
        occurred_at=merge.created_at,
        content=merge.reason or "Gộp hồ sơ khách hàng",
        created_by=merge.created_by,
        metadata={
            "survivor_customer_id": merge.survivor_customer_id,
            "source_customer_id": merge.source_customer_id,
            "before_counts": merge.before_counts,
            "after_counts": merge.after_counts,
        },
    ) for merge in merges)
    items.extend(CustomerTimelineItem(
        event_type="customer_profile",
        event_id=audit.id,
        occurred_at=audit.created_at,
        content="Cập nhật hồ sơ khách hàng" if audit.action == "profile_update" else "Tạo hồ sơ khách hàng",
        created_by=audit.user_id,
        metadata={"action": audit.action, **(audit.metadata_ or {})},
    ) for audit in profile_history)
    items.extend(CustomerTimelineItem(
        event_type="customer_tag",
        event_id=audit.id,
        occurred_at=audit.created_at,
        content=(
            f"Gắn tag {audit.metadata_.get('tag')}"
            if audit.action == "tag_add"
            else f"Bỏ tag {audit.metadata_.get('tag') or audit.metadata_.get('tag_id')}"
        ),
        created_by=audit.user_id,
        metadata={"action": audit.action, **(audit.metadata_ or {})},
    ) for audit in tag_history)
    items.extend(CustomerTimelineItem(
        event_type="customer_merge_undo",
        event_id=audit.id,
        occurred_at=audit.created_at,
        content=(audit.metadata_ or {}).get("reason") or "Hoàn tác gộp hồ sơ khách hàng",
        created_by=audit.user_id,
        metadata={"action": audit.action, **(audit.metadata_ or {})},
    ) for audit in merge_undo_history)
    items.sort(key=lambda item: item.occurred_at or datetime.min, reverse=True)
    total = len(items)
    page = items[offset : offset + limit]
    has_more = offset + len(page) < total
    return CustomerTimelineOut(
        items=page,
        total=total,
        offset=offset,
        limit=limit,
        has_more=has_more,
        next_offset=offset + len(page) if has_more else None,
    )


@router.post("/{customer_id}/notes", response_model=CustomerNoteOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_customer_note(
    customer_id: int,
    payload: CustomerNoteCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    _get_customer(db, customer_id, tenant)
    note = CustomerNote(
        business_id=tenant.business_id,
        customer_id=customer_id,
        content=payload.content.strip(),
    )
    if not note.content:
        raise HTTPException(status_code=422, detail="Nội dung note không được rỗng.")
    db.add(note)
    db.commit()
    db.refresh(note)
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="note_create",
        resource_type="customer_note",
        resource_id=str(note.id),
        metadata={"customer_id": customer_id},
    )
    db.commit()
    return note
