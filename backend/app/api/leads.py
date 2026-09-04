"""Tenant-scoped lead and sales pipeline APIs."""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db.dependencies import get_db
from app.models.business import User
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.lead import Lead
from app.schemas.lead import (
    LeadCreate,
    LeadListOut,
    LeadOut,
    LeadUpdate,
    PipelineReportOut,
    PipelineStageItem,
    PIPELINE_STAGES,
)
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.services.workflow_engine import emit_workflow_event
from app.auth.dependencies import require_write_access


router = APIRouter()


def _validate_stage(stage: str | None) -> None:
    if stage is not None and stage not in PIPELINE_STAGES:
        raise HTTPException(status_code=422, detail=f"Stage không hợp lệ. Chọn một trong: {', '.join(PIPELINE_STAGES)}")


def _get_customer(db: Session, customer_id: int, tenant: TenantContext) -> Customer:
    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.business_id == tenant.business_id,
    ).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer không tồn tại.")
    return customer


def _get_conversation(db: Session, conversation_id: int, customer_id: int, tenant: TenantContext) -> Conversation:
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == tenant.business_id,
        Conversation.customer_id == customer_id,
    ).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation không thuộc customer/business này.")
    return conversation


def _validate_assignee(db: Session, user_id: int | None, tenant: TenantContext) -> None:
    if user_id is None:
        return
    user = db.query(User).filter(
        User.id == user_id,
        User.business_id == tenant.business_id,
        User.is_active.is_(True),
    ).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Nhân viên không thuộc business hoặc đã bị vô hiệu hóa.")


def _get_lead(db: Session, lead_id: int, tenant: TenantContext) -> Lead:
    lead = db.query(Lead).options(
        joinedload(Lead.customer),
        joinedload(Lead.conversation),
    ).filter(
        Lead.id == lead_id,
        Lead.business_id == tenant.business_id,
    ).first()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead không tồn tại.")
    return lead


def _out(lead: Lead) -> LeadOut:
    return LeadOut(
        id=lead.id,
        business_id=lead.business_id,
        customer_id=lead.customer_id,
        conversation_id=lead.conversation_id,
        title=lead.title,
        stage=lead.stage,
        status=lead.status,
        value=lead.value,
        probability=lead.probability,
        source_channel=lead.source_channel,
        assigned_user_id=lead.assigned_user_id,
        expected_close_at=lead.expected_close_at,
        notes=lead.notes,
        metadata=lead.metadata_,
        customer_name=lead.customer.name if lead.customer else None,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


@router.get("/leads", response_model=LeadListOut)
def list_leads(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    stage: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    _validate_stage(stage)
    query = db.query(Lead).options(joinedload(Lead.customer)).filter(Lead.business_id == tenant.business_id)
    if stage:
        query = query.filter(Lead.stage == stage)
    if status:
        query = query.filter(Lead.status == status)
    total = query.count()
    leads = query.order_by(Lead.updated_at.desc(), Lead.id.desc()).offset(offset).limit(limit).all()
    return LeadListOut(items=[_out(lead) for lead in leads], total=total)


@router.post("/leads", response_model=LeadOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_lead(
    payload: LeadCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    _validate_stage(payload.stage)
    customer = _get_customer(db, payload.customer_id, tenant)
    conversation = None
    if payload.conversation_id is not None:
        conversation = _get_conversation(db, payload.conversation_id, customer.id, tenant)
    _validate_assignee(db, payload.assigned_user_id, tenant)
    lead = Lead(
        business_id=tenant.business_id,
        customer_id=customer.id,
        conversation_id=conversation.id if conversation else None,
        title=payload.title.strip(),
        stage=payload.stage,
        status=payload.status,
        value=payload.value,
        probability=payload.probability,
        source_channel=payload.source_channel or (conversation.channel if conversation else None),
        assigned_user_id=payload.assigned_user_id,
        expected_close_at=payload.expected_close_at,
        notes=payload.notes.strip() if payload.notes else None,
        metadata_=payload.metadata,
    )
    db.add(lead)
    db.commit()
    emit_workflow_event(
        db,
        tenant,
        "lead.stage_changed",
        f"lead:{lead.id}:stage:{lead.stage}",
        {"lead_id": lead.id, "customer_id": lead.customer_id, "conversation_id": lead.conversation_id, "stage": lead.stage, "value": float(lead.value or 0)},
    )
    return _out(_get_lead(db, lead.id, tenant))


@router.get("/leads/{lead_id}", response_model=LeadOut)
def get_lead(lead_id: int, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    return _out(_get_lead(db, lead_id, tenant))


@router.patch("/leads/{lead_id}", response_model=LeadOut, dependencies=[Depends(require_write_access)])
def update_lead(
    lead_id: int,
    payload: LeadUpdate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    lead = _get_lead(db, lead_id, tenant)
    previous_stage = lead.stage
    data = payload.model_dump(exclude_unset=True)
    _validate_stage(data.get("stage"))
    customer_id = data.get("customer_id", lead.customer_id)
    _get_customer(db, customer_id, tenant)
    if customer_id != lead.customer_id and "conversation_id" not in data:
        # A conversation belongs to exactly one customer; detach it when the
        # lead is moved to a different customer unless a new one is supplied.
        data["conversation_id"] = None
        data["source_channel"] = None
    if "conversation_id" in data and data["conversation_id"] is not None:
        conversation = _get_conversation(db, data["conversation_id"], customer_id, tenant)
        data["source_channel"] = data.get("source_channel") or conversation.channel
    _validate_assignee(db, data.get("assigned_user_id", lead.assigned_user_id), tenant)
    for field, value in data.items():
        field = "metadata_" if field == "metadata" else field
        if field in {"title", "notes", "source_channel"} and isinstance(value, str):
            value = value.strip() or None
        setattr(lead, field, value)
    db.commit()
    if "stage" in data and data["stage"] != previous_stage:
        emit_workflow_event(
            db,
            tenant,
            "lead.stage_changed",
            f"lead:{lead.id}:stage:{lead.stage}",
            {"lead_id": lead.id, "customer_id": lead.customer_id, "conversation_id": lead.conversation_id, "stage": lead.stage, "value": float(lead.value or 0)},
        )
    return _out(_get_lead(db, lead_id, tenant))


@router.get("/reports/pipeline", response_model=PipelineReportOut)
def pipeline_report(db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    rows = db.query(
        Lead.stage.label("stage"),
        func.count(Lead.id).label("lead_count"),
        func.coalesce(func.sum(Lead.value), Decimal("0")).label("value"),
    ).filter(Lead.business_id == tenant.business_id).group_by(Lead.stage).order_by(Lead.stage.asc()).all()
    items = [PipelineStageItem(stage=str(row.stage), lead_count=int(row.lead_count), value=Decimal(row.value or 0)) for row in rows]
    return PipelineReportOut(
        items=items,
        total_leads=sum(item.lead_count for item in items),
        total_value=sum((item.value for item in items), Decimal("0")),
    )
