"""Quotes, projects, and receivables for service and B2B shops."""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import require_write_access
from app.db.dependencies import get_db
from app.database.platform_session import get_platform_db
from app.models.business import User
from app.models.customer import Customer
from app.models.industry_modules import CommercialInvoice, CommercialInvoicePayment, CommercialProject, CommercialQuote
from app.tenancy.context import TenantContext
from app.tenancy.crm_session import get_tenant_db
from app.tenancy.dependencies import get_tenant_context
from app.tenancy.workspace_modules import require_module_enabled
from app.services.workflow_engine import emit_workflow_event
from app.services.customer_collection import customer_email_for_delivery
from app.services.notification_service import deliver_notification_email


router = APIRouter(prefix="/commercial", dependencies=[Depends(require_module_enabled("projects"))])
QuoteStatus = Literal["draft", "sent", "accepted", "rejected", "expired"]
ProjectStatus = Literal["planned", "active", "on_hold", "completed", "cancelled"]
InvoiceStatus = Literal["draft", "issued", "void"]
CENT = Decimal("0.01")


class QuoteLine(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0, le=1000000)
    unit_price: Decimal = Field(ge=0, le=9999999999)


class QuoteCreate(BaseModel):
    customer_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    items: list[QuoteLine] = Field(min_length=1, max_length=100)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    valid_until: date | None = None
    notes: str | None = Field(default=None, max_length=4000)


class QuoteUpdate(BaseModel):
    customer_id: int | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    items: list[QuoteLine] | None = Field(default=None, min_length=1, max_length=100)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100)
    valid_until: date | None = None
    notes: str | None = Field(default=None, max_length=4000)
    status: QuoteStatus | None = None


class ProjectCreate(BaseModel):
    customer_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    quote_id: int | None = Field(default=None, gt=0)
    status: ProjectStatus = "planned"
    budget: Decimal = Field(default=Decimal("0"), ge=0, le=9999999999)
    starts_on: date | None = None
    due_on: date | None = None
    assigned_user_id: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, max_length=4000)


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: ProjectStatus | None = None
    budget: Decimal | None = Field(default=None, ge=0, le=9999999999)
    starts_on: date | None = None
    due_on: date | None = None
    assigned_user_id: int | None = None
    description: str | None = Field(default=None, max_length=4000)


class InvoiceCreate(BaseModel):
    customer_id: int = Field(gt=0)
    project_id: int | None = Field(default=None, gt=0)
    quote_id: int | None = Field(default=None, gt=0)
    description: str = Field(min_length=1, max_length=240)
    total_amount: Decimal = Field(gt=0, le=9999999999)
    status: Literal["draft", "issued"] = "draft"
    issued_on: date | None = None
    due_on: date | None = None
    notes: str | None = Field(default=None, max_length=4000)


class InvoiceUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    description: str | None = Field(default=None, min_length=1, max_length=240)
    total_amount: Decimal | None = Field(default=None, gt=0, le=9999999999)
    status: InvoiceStatus | None = None
    issued_on: date | None = None
    due_on: date | None = None
    notes: str | None = Field(default=None, max_length=4000)


class InvoicePaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0, le=9999999999)
    paid_on: date = Field(default_factory=date.today)
    method: Literal["bank_transfer", "cash", "card", "other"] = "bank_transfer"
    reference: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _customer(db: Session, customer_id: int, tenant: TenantContext) -> Customer:
    row = db.query(Customer).filter(Customer.id == customer_id, Customer.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Khách hàng không thuộc shop này.")
    return row


def _assignee(user_db: Session, user_id: int | None, tenant: TenantContext) -> None:
    if user_id is None:
        return
    if user_db.query(User.id).filter(User.id == user_id, User.business_id == tenant.business_id, User.is_active.is_(True)).first() is None:
        raise HTTPException(status_code=404, detail="Nhân viên không thuộc shop hoặc đã bị vô hiệu hóa.")


def _customer_name(db: Session, customer_id: int, business_id: int) -> str | None:
    customer = db.query(Customer).filter(Customer.id == customer_id, Customer.business_id == business_id).first()
    return customer.name if customer else None


def _quote_amounts(items: list[QuoteLine]) -> tuple[list[dict], Decimal]:
    normalized = []
    subtotal = Decimal("0")
    for item in items:
        name = item.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Mỗi dòng báo giá cần có tên.")
        line_total = _money(item.quantity * item.unit_price)
        subtotal += line_total
        normalized.append({
            "name": name,
            "quantity": str(item.quantity.normalize()),
            "unit_price": str(_money(item.unit_price)),
            "total": str(line_total),
        })
    return normalized, _money(subtotal)


def _quote_totals(items: list[QuoteLine], tax_rate: Decimal) -> tuple[list[dict], Decimal, Decimal, Decimal]:
    normalized, subtotal = _quote_amounts(items)
    tax_amount = _money(subtotal * tax_rate / Decimal("100"))
    return normalized, subtotal, tax_amount, _money(subtotal + tax_amount)


def _quote_out(db: Session, row: CommercialQuote) -> dict:
    return {
        "id": row.id, "business_id": row.business_id, "customer_id": row.customer_id,
        "customer_name": _customer_name(db, row.customer_id, row.business_id),
        "quote_number": row.quote_number, "title": row.title, "status": row.status,
        "items": row.items, "subtotal": row.subtotal, "tax_rate": row.tax_rate,
        "tax_amount": row.tax_amount, "total_amount": row.total_amount,
        "valid_until": row.valid_until, "notes": row.notes,
        "email_sent_at": row.email_sent_at, "created_at": row.created_at,
    }


def _project_out(db: Session, row: CommercialProject) -> dict:
    return {
        "id": row.id, "business_id": row.business_id, "customer_id": row.customer_id,
        "customer_name": _customer_name(db, row.customer_id, row.business_id), "quote_id": row.quote_id,
        "title": row.title, "status": row.status, "budget": row.budget,
        "starts_on": row.starts_on, "due_on": row.due_on, "assigned_user_id": row.assigned_user_id,
        "description": row.description, "created_at": row.created_at,
    }


def _invoice_status(row: CommercialInvoice) -> str:
    if row.status == "void":
        return "void"
    if row.paid_amount >= row.total_amount:
        return "paid"
    if row.status == "issued" and row.due_on is not None and row.due_on < date.today():
        return "overdue"
    return row.status


def _invoice_out(db: Session, row: CommercialInvoice) -> dict:
    payments = db.query(CommercialInvoicePayment).filter(
        CommercialInvoicePayment.business_id == row.business_id,
        CommercialInvoicePayment.invoice_id == row.id,
    ).order_by(CommercialInvoicePayment.paid_on.desc(), CommercialInvoicePayment.id.desc()).all()
    return {
        "id": row.id, "business_id": row.business_id, "customer_id": row.customer_id,
        "customer_name": _customer_name(db, row.customer_id, row.business_id), "project_id": row.project_id,
        "quote_id": row.quote_id, "invoice_number": row.invoice_number, "description": row.description,
        "total_amount": row.total_amount, "paid_amount": row.paid_amount, "balance_due": _money(row.total_amount - row.paid_amount),
        "status": _invoice_status(row), "issued_on": row.issued_on, "due_on": row.due_on,
        "email_sent_at": row.email_sent_at,
        "payments": payments,
        "notes": row.notes, "created_at": row.created_at,
    }


@router.get("/quotes")
def list_quotes(
    db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context),
    status: QuoteStatus | None = None, limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
):
    query = db.query(CommercialQuote).filter(CommercialQuote.business_id == tenant.business_id)
    if status:
        query = query.filter(CommercialQuote.status == status)
    total = query.count()
    rows = query.order_by(CommercialQuote.updated_at.desc(), CommercialQuote.id.desc()).offset(offset).limit(limit).all()
    return {"items": [_quote_out(db, row) for row in rows], "total": total}


@router.post("/quotes", status_code=201, dependencies=[Depends(require_write_access)])
def create_quote(payload: QuoteCreate, db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context), platform_db: Session = Depends(get_platform_db)):
    if not payload.title.strip():
        raise HTTPException(status_code=422, detail="Tiêu đề báo giá không được để trống.")
    _customer(db, payload.customer_id, tenant)
    items, subtotal, tax_amount, total = _quote_totals(payload.items, payload.tax_rate)
    row = CommercialQuote(
        business_id=tenant.business_id, customer_id=payload.customer_id, quote_number="pending",
        title=payload.title.strip(), items=items, subtotal=subtotal, tax_rate=payload.tax_rate,
        tax_amount=tax_amount, total_amount=total, valid_until=payload.valid_until,
        notes=payload.notes.strip() if payload.notes else None,
    )
    db.add(row)
    db.flush()
    row.quote_number = f"Q-{date.today():%Y%m}-{row.id:06d}"
    db.commit()
    db.refresh(row)
    emit_workflow_event(db, tenant, "quote.created", f"quote:{row.id}:created", {"quote_id": row.id, "customer_id": row.customer_id, "status": row.status, "total_amount": float(row.total_amount)}, platform_db=platform_db)
    return _quote_out(db, row)


@router.patch("/quotes/{quote_id}", dependencies=[Depends(require_write_access)])
def update_quote(quote_id: int, payload: QuoteUpdate, db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context), platform_db: Session = Depends(get_platform_db)):
    row = db.query(CommercialQuote).filter(CommercialQuote.id == quote_id, CommercialQuote.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Báo giá không tồn tại.")
    previous_status = row.status
    changes = payload.model_dump(exclude_unset=True)
    if any(key in changes and changes[key] is None for key in ("customer_id", "title", "status", "tax_rate")):
        raise HTTPException(status_code=422, detail="Khách hàng, tiêu đề, trạng thái và thuế không được để trống.")
    if "customer_id" in changes and changes["customer_id"] is not None:
        _customer(db, changes["customer_id"], tenant)
    if "title" in changes and changes["title"] is not None:
        row.title = changes.pop("title").strip()
    if "items" in changes and changes["items"] is not None:
        changes["items"], row.subtotal = _quote_amounts(payload.items)
    if "tax_rate" in changes and changes["tax_rate"] is not None:
        row.tax_rate = changes.pop("tax_rate")
    if "items" in payload.model_fields_set or "tax_rate" in payload.model_fields_set:
        row.tax_amount = _money(row.subtotal * row.tax_rate / Decimal("100"))
        row.total_amount = _money(row.subtotal + row.tax_amount)
    for key, value in changes.items():
        if key == "items" or value is None and key in {"customer_id", "status", "tax_rate", "title"}:
            continue
        setattr(row, key, value.strip() if key == "notes" and value else value)
    db.commit()
    db.refresh(row)
    if row.status != previous_status:
        emit_workflow_event(db, tenant, "quote.status_changed", f"quote:{row.id}:status:{row.status}:{row.updated_at}", {"quote_id": row.id, "customer_id": row.customer_id, "from_status": previous_status, "status": row.status, "total_amount": float(row.total_amount)}, platform_db=platform_db)
    return _quote_out(db, row)


@router.post("/quotes/{quote_id}/send-email", dependencies=[Depends(require_write_access)])
def send_quote_email(quote_id: int, db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context)):
    row = db.query(CommercialQuote).filter(
        CommercialQuote.id == quote_id,
        CommercialQuote.business_id == tenant.business_id,
    ).with_for_update().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Báo giá không tồn tại.")
    if row.status not in {"draft", "sent"}:
        raise HTTPException(status_code=409, detail="Chỉ có thể gửi báo giá đang ở trạng thái nháp hoặc đã gửi.")
    if row.email_sent_at is not None:
        raise HTTPException(status_code=409, detail="Báo giá này đã được gửi qua email.")
    recipient = customer_email_for_delivery(db, business_id=tenant.business_id, customer_id=row.customer_id)
    if not recipient:
        raise HTTPException(status_code=422, detail="Khách hàng chưa có email hợp lệ.")
    lines = [f"- {item['name']}: {item['quantity']} × {item['unit_price']} = {item['total']} đ" for item in row.items or []]
    body = "\n".join([
        f"Xin chào {_customer_name(db, row.customer_id, tenant.business_id) or 'quý khách'},",
        "",
        f"Shop gửi báo giá {row.quote_number}: {row.title}.",
        *lines,
        f"Tạm tính: {row.subtotal} đ",
        f"Thuế: {row.tax_rate}% ({row.tax_amount} đ)",
        f"Tổng cộng: {row.total_amount} đ",
        f"Hiệu lực đến: {row.valid_until}" if row.valid_until else "",
        f"Ghi chú: {row.notes}" if row.notes else "",
        "",
        "Trân trọng,",
        "Smart Merchant Hub",
    ])
    if not deliver_notification_email(recipient_email=recipient, title=f"Báo giá {row.quote_number} - {row.title}", body=body):
        raise HTTPException(status_code=503, detail="Chưa gửi được email. Kiểm tra cấu hình SMTP rồi thử lại.")
    row.status = "sent"
    row.email_sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(row)
    return _quote_out(db, row)


@router.post("/quotes/{quote_id}/project", status_code=201, dependencies=[Depends(require_write_access)])
def convert_quote_to_project(quote_id: int, db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context), platform_db: Session = Depends(get_platform_db)):
    quote = db.query(CommercialQuote).filter(CommercialQuote.id == quote_id, CommercialQuote.business_id == tenant.business_id).with_for_update().first()
    if quote is None:
        raise HTTPException(status_code=404, detail="Báo giá không tồn tại.")
    if quote.status != "accepted":
        raise HTTPException(status_code=409, detail="Chỉ báo giá đã được khách chấp thuận mới chuyển thành dự án được.")
    existing = db.query(CommercialProject).filter(CommercialProject.business_id == tenant.business_id, CommercialProject.quote_id == quote.id).first()
    if existing:
        return _project_out(db, existing)
    project = CommercialProject(
        business_id=tenant.business_id, customer_id=quote.customer_id, quote_id=quote.id,
        title=quote.title, status="planned", budget=quote.total_amount,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    emit_workflow_event(db, tenant, "project.created", f"project:{project.id}:created", {"project_id": project.id, "customer_id": project.customer_id, "quote_id": project.quote_id, "status": project.status, "budget": float(project.budget)}, platform_db=platform_db)
    return _project_out(db, project)


@router.get("/projects")
def list_projects(
    db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context),
    status: ProjectStatus | None = None, limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
):
    query = db.query(CommercialProject).filter(CommercialProject.business_id == tenant.business_id)
    if status:
        query = query.filter(CommercialProject.status == status)
    total = query.count()
    rows = query.order_by(CommercialProject.updated_at.desc(), CommercialProject.id.desc()).offset(offset).limit(limit).all()
    return {"items": [_project_out(db, row) for row in rows], "total": total}


@router.post("/projects", status_code=201, dependencies=[Depends(require_write_access)])
def create_project(
    payload: ProjectCreate, db: Session = Depends(get_tenant_db), user_db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context), platform_db: Session = Depends(get_platform_db),
):
    if not payload.title.strip():
        raise HTTPException(status_code=422, detail="Tên dự án không được để trống.")
    _customer(db, payload.customer_id, tenant)
    if payload.quote_id is not None:
        quote = db.query(CommercialQuote).filter(
            CommercialQuote.id == payload.quote_id, CommercialQuote.business_id == tenant.business_id,
            CommercialQuote.customer_id == payload.customer_id, CommercialQuote.status == "accepted",
        ).first()
        if quote is None:
            raise HTTPException(status_code=422, detail="Báo giá phải thuộc khách hàng và shop này, đồng thời đã được chấp thuận.")
        existing = db.query(CommercialProject).filter(CommercialProject.business_id == tenant.business_id, CommercialProject.quote_id == quote.id).first()
        if existing:
            return _project_out(db, existing)
    if payload.starts_on and payload.due_on and payload.due_on < payload.starts_on:
        raise HTTPException(status_code=422, detail="Ngày kết thúc không thể trước ngày bắt đầu.")
    _assignee(user_db, payload.assigned_user_id, tenant)
    row = CommercialProject(
        business_id=tenant.business_id, customer_id=payload.customer_id, quote_id=payload.quote_id,
        title=payload.title.strip(), status=payload.status, budget=payload.budget,
        starts_on=payload.starts_on, due_on=payload.due_on, assigned_user_id=payload.assigned_user_id,
        description=payload.description.strip() if payload.description else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    emit_workflow_event(db, tenant, "project.created", f"project:{row.id}:created", {"project_id": row.id, "customer_id": row.customer_id, "quote_id": row.quote_id, "status": row.status, "budget": float(row.budget)}, platform_db=platform_db)
    return _project_out(db, row)


@router.patch("/projects/{project_id}", dependencies=[Depends(require_write_access)])
def update_project(
    project_id: int, payload: ProjectUpdate, db: Session = Depends(get_tenant_db), user_db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context), platform_db: Session = Depends(get_platform_db),
):
    row = db.query(CommercialProject).filter(CommercialProject.id == project_id, CommercialProject.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Dự án không tồn tại.")
    previous_status = row.status
    changes = payload.model_dump(exclude_unset=True)
    if any(key in changes and changes[key] is None for key in ("title", "status", "budget")):
        raise HTTPException(status_code=422, detail="Tên, trạng thái và ngân sách không được để trống.")
    start = changes.get("starts_on", row.starts_on)
    due = changes.get("due_on", row.due_on)
    if start and due and due < start:
        raise HTTPException(status_code=422, detail="Ngày kết thúc không thể trước ngày bắt đầu.")
    if "assigned_user_id" in changes:
        _assignee(user_db, changes["assigned_user_id"], tenant)
    for key, value in changes.items():
        setattr(row, key, value.strip() if key in {"title", "description"} and value else value)
    db.commit()
    db.refresh(row)
    if row.status != previous_status:
        emit_workflow_event(db, tenant, "project.status_changed", f"project:{row.id}:status:{row.status}:{row.updated_at}", {"project_id": row.id, "customer_id": row.customer_id, "from_status": previous_status, "status": row.status, "budget": float(row.budget)}, platform_db=platform_db)
    return _project_out(db, row)


@router.get("/invoices")
def list_invoices(
    db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context),
    status: Literal["draft", "issued", "paid", "overdue", "void"] | None = None,
    limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
):
    query = db.query(CommercialInvoice).filter(CommercialInvoice.business_id == tenant.business_id)
    # Use persisted status for inexpensive filtering, then derive overdue/paid on output.
    if status in {"draft", "issued", "void"}:
        query = query.filter(CommercialInvoice.status == status)
    elif status == "paid":
        query = query.filter(CommercialInvoice.paid_amount >= CommercialInvoice.total_amount)
    elif status == "overdue":
        query = query.filter(CommercialInvoice.status == "issued", CommercialInvoice.due_on < date.today(), CommercialInvoice.paid_amount < CommercialInvoice.total_amount)
    total = query.count()
    rows = query.order_by(CommercialInvoice.due_on.asc().nullslast(), CommercialInvoice.id.desc()).offset(offset).limit(limit).all()
    return {"items": [_invoice_out(db, row) for row in rows], "total": total}


@router.post("/invoices", status_code=201, dependencies=[Depends(require_write_access)])
def create_invoice(payload: InvoiceCreate, db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context), platform_db: Session = Depends(get_platform_db)):
    if not payload.description.strip():
        raise HTTPException(status_code=422, detail="Mô tả hóa đơn không được để trống.")
    if payload.issued_on and payload.due_on and payload.due_on < payload.issued_on:
        raise HTTPException(status_code=422, detail="Hạn thanh toán không thể trước ngày phát hành.")
    _customer(db, payload.customer_id, tenant)
    project = None
    quote = None
    if payload.project_id is not None:
        project = db.query(CommercialProject).filter(
            CommercialProject.id == payload.project_id, CommercialProject.business_id == tenant.business_id,
            CommercialProject.customer_id == payload.customer_id,
        ).first()
        if project is None:
            raise HTTPException(status_code=404, detail="Dự án không thuộc khách hàng/shop này.")
    if payload.quote_id is not None:
        quote = db.query(CommercialQuote).filter(
            CommercialQuote.id == payload.quote_id, CommercialQuote.business_id == tenant.business_id,
            CommercialQuote.customer_id == payload.customer_id,
        ).first()
        if quote is None:
            raise HTTPException(status_code=404, detail="Báo giá không thuộc khách hàng/shop này.")
    if project and quote and project.quote_id != quote.id:
        raise HTTPException(status_code=422, detail="Báo giá không phải nguồn của dự án đã chọn.")
    row = CommercialInvoice(
        business_id=tenant.business_id, customer_id=payload.customer_id, project_id=project.id if project else None,
        quote_id=quote.id if quote else None, invoice_number="pending", description=payload.description.strip(),
        total_amount=_money(payload.total_amount), paid_amount=Decimal("0"), status=payload.status,
        issued_on=payload.issued_on or (date.today() if payload.status == "issued" else None),
        due_on=payload.due_on, notes=payload.notes.strip() if payload.notes else None,
    )
    db.add(row)
    db.flush()
    row.invoice_number = f"INV-{date.today():%Y%m}-{row.id:06d}"
    db.commit()
    db.refresh(row)
    emit_workflow_event(db, tenant, "invoice.created", f"invoice:{row.id}:created", {"invoice_id": row.id, "customer_id": row.customer_id, "project_id": row.project_id, "status": _invoice_status(row), "total_amount": float(row.total_amount)}, platform_db=platform_db)
    return _invoice_out(db, row)


@router.patch("/invoices/{invoice_id}", dependencies=[Depends(require_write_access)])
def update_invoice(invoice_id: int, payload: InvoiceUpdate, db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context), platform_db: Session = Depends(get_platform_db)):
    row = db.query(CommercialInvoice).filter(CommercialInvoice.id == invoice_id, CommercialInvoice.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Hóa đơn không tồn tại.")
    previous_status = _invoice_status(row)
    changes = payload.model_dump(exclude_unset=True)
    if any(key in changes and changes[key] is None for key in ("description", "total_amount", "status")):
        raise HTTPException(status_code=422, detail="Mô tả, số tiền và trạng thái không được để trống.")
    total_amount = _money(changes.get("total_amount", row.total_amount) or row.total_amount)
    paid_amount = _money(row.paid_amount)
    issued_on = changes.get("issued_on", row.issued_on)
    due_on = changes.get("due_on", row.due_on)
    if issued_on and due_on and due_on < issued_on:
        raise HTTPException(status_code=422, detail="Hạn thanh toán không thể trước ngày phát hành.")
    if paid_amount > total_amount:
        raise HTTPException(status_code=409, detail="Không thể giảm tổng hóa đơn xuống dưới số tiền đã thu.")
    if changes.get("status") == "void" and paid_amount > 0:
        raise HTTPException(status_code=409, detail="Hóa đơn đã có thanh toán; cần xử lý khoản hoàn trước khi hủy.")
    for key, value in changes.items():
        if key == "total_amount":
            value = _money(value)
        if key in {"description", "notes"} and value:
            value = value.strip()
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    if _invoice_status(row) != previous_status:
        emit_workflow_event(db, tenant, "invoice.status_changed", f"invoice:{row.id}:status:{_invoice_status(row)}:{row.updated_at}", {"invoice_id": row.id, "customer_id": row.customer_id, "from_status": previous_status, "status": _invoice_status(row), "total_amount": float(row.total_amount)}, platform_db=platform_db)
    return _invoice_out(db, row)


@router.post("/invoices/{invoice_id}/send-email", dependencies=[Depends(require_write_access)])
def send_invoice_email(invoice_id: int, db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context)):
    row = db.query(CommercialInvoice).filter(
        CommercialInvoice.id == invoice_id,
        CommercialInvoice.business_id == tenant.business_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Hóa đơn không tồn tại.")
    if row.status != "issued":
        raise HTTPException(status_code=409, detail="Chỉ có thể gửi hóa đơn đã phát hành.")
    if row.email_sent_at is not None:
        raise HTTPException(status_code=409, detail="Hóa đơn này đã được gửi qua email.")
    recipient = customer_email_for_delivery(db, business_id=tenant.business_id, customer_id=row.customer_id)
    if not recipient:
        raise HTTPException(status_code=422, detail="Khách hàng chưa có email hợp lệ.")
    body = "\n".join([
        f"Xin chào {_customer_name(db, row.customer_id, tenant.business_id) or 'quý khách'},",
        "",
        f"Shop gửi hóa đơn {row.invoice_number}: {row.description}.",
        f"Tổng hóa đơn: {row.total_amount} đ",
        f"Đã thanh toán: {row.paid_amount} đ",
        f"Còn phải thanh toán: {_money(row.total_amount - row.paid_amount)} đ",
        f"Ngày phát hành: {row.issued_on}" if row.issued_on else "",
        f"Hạn thanh toán: {row.due_on}" if row.due_on else "",
        f"Ghi chú: {row.notes}" if row.notes else "",
        "",
        "Trân trọng,",
        "Smart Merchant Hub",
    ])
    if not deliver_notification_email(recipient_email=recipient, title=f"Hóa đơn {row.invoice_number}", body=body):
        raise HTTPException(status_code=503, detail="Chưa gửi được email. Kiểm tra cấu hình SMTP rồi thử lại.")
    row.email_sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(row)
    return _invoice_out(db, row)


@router.post("/invoices/{invoice_id}/payments", status_code=201, dependencies=[Depends(require_write_access)])
def record_invoice_payment(
    invoice_id: int, payload: InvoicePaymentCreate, db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context), platform_db: Session = Depends(get_platform_db),
):
    row = db.query(CommercialInvoice).filter(
        CommercialInvoice.id == invoice_id,
        CommercialInvoice.business_id == tenant.business_id,
    ).with_for_update().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Hóa đơn không tồn tại.")
    if row.status != "issued":
        raise HTTPException(status_code=409, detail="Chỉ ghi nhận thanh toán cho hóa đơn đã phát hành.")
    previous_status = _invoice_status(row)
    amount = _money(payload.amount)
    if amount <= 0 or amount > _money(row.total_amount - row.paid_amount):
        raise HTTPException(status_code=422, detail="Khoản thu phải lớn hơn 0 và không vượt số dư còn lại.")
    db.add(CommercialInvoicePayment(
        business_id=tenant.business_id,
        invoice_id=row.id,
        amount=amount,
        paid_on=payload.paid_on,
        method=payload.method,
        reference=payload.reference.strip() if payload.reference else None,
        notes=payload.notes.strip() if payload.notes else None,
    ))
    row.paid_amount = _money(row.paid_amount + amount)
    db.commit()
    db.refresh(row)
    emit_workflow_event(db, tenant, "invoice.payment_recorded", f"invoice:{row.id}:payment:{row.paid_amount}", {"invoice_id": row.id, "customer_id": row.customer_id, "amount": float(amount), "paid_amount": float(row.paid_amount), "status": _invoice_status(row)}, platform_db=platform_db)
    if _invoice_status(row) != previous_status:
        emit_workflow_event(db, tenant, "invoice.status_changed", f"invoice:{row.id}:status:{_invoice_status(row)}:{row.updated_at}", {"invoice_id": row.id, "customer_id": row.customer_id, "from_status": previous_status, "status": _invoice_status(row), "total_amount": float(row.total_amount)}, platform_db=platform_db)
    return _invoice_out(db, row)
