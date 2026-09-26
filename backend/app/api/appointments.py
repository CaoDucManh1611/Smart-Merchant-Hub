"""Service catalog and appointment scheduling APIs."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import require_write_access
from app.db.dependencies import get_db
from app.database.platform_session import get_platform_db
from app.models.business import User
from app.models.customer import Customer
from app.models.crm_job import CrmJob
from app.models.industry_modules import Appointment, AppointmentService
from app.services.customer_collection import customer_email_for_delivery
from app.services.job_service import enqueue_job
from app.services.workflow_engine import emit_workflow_event
from app.tenancy.context import TenantContext
from app.tenancy.crm_session import get_tenant_db
from app.tenancy.dependencies import get_tenant_context
from app.tenancy.workspace_modules import require_module_enabled


router = APIRouter(prefix="/appointments", dependencies=[Depends(require_module_enabled("appointments"))])
AppointmentStatus = Literal["scheduled", "confirmed", "completed", "cancelled", "no_show"]


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    duration_minutes: int = Field(default=60, ge=5, le=1440)
    price: Decimal = Field(default=Decimal("0"), ge=0, le=9999999999)


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    duration_minutes: int | None = Field(default=None, ge=5, le=1440)
    price: Decimal | None = Field(default=None, ge=0, le=9999999999)
    is_active: bool | None = None


class AppointmentCreate(BaseModel):
    customer_id: int = Field(gt=0)
    service_id: int = Field(gt=0)
    starts_at: datetime
    assigned_user_id: int | None = Field(default=None, gt=0)
    reminder_minutes_before: int = Field(default=60, ge=0, le=10080)
    send_customer_reminder: bool = False
    notes: str | None = Field(default=None, max_length=4000)


class AppointmentUpdate(BaseModel):
    customer_id: int | None = Field(default=None, gt=0)
    service_id: int | None = Field(default=None, gt=0)
    starts_at: datetime | None = None
    assigned_user_id: int | None = Field(default=None, ge=1)
    status: AppointmentStatus | None = None
    reminder_minutes_before: int | None = Field(default=None, ge=0, le=10080)
    send_customer_reminder: bool | None = None
    notes: str | None = Field(default=None, max_length=4000)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _customer(db: Session, customer_id: int, tenant: TenantContext) -> Customer:
    row = db.query(Customer).filter(Customer.id == customer_id, Customer.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Khách hàng không thuộc shop này.")
    return row


def _service(db: Session, service_id: int, tenant: TenantContext, *, active: bool = True) -> AppointmentService:
    query = db.query(AppointmentService).filter(
        AppointmentService.id == service_id,
        AppointmentService.business_id == tenant.business_id,
    )
    if active:
        query = query.filter(AppointmentService.is_active.is_(True))
    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Dịch vụ không tồn tại hoặc đã ngừng nhận lịch.")
    return row


def _assignee(user_db: Session, user_id: int | None, tenant: TenantContext) -> None:
    if user_id is None:
        return
    user = user_db.query(User.id).filter(
        User.id == user_id,
        User.business_id == tenant.business_id,
        User.is_active.is_(True),
    ).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Nhân viên không thuộc shop hoặc đã bị vô hiệu hóa.")


def _ensure_no_conflict(
    db: Session, tenant: TenantContext, starts_at: datetime, ends_at: datetime,
    assigned_user_id: int | None, *, exclude_id: int | None = None,
) -> None:
    if assigned_user_id is None:
        return
    query = db.query(Appointment.id).filter(
        Appointment.business_id == tenant.business_id,
        Appointment.assigned_user_id == assigned_user_id,
        Appointment.status.in_(("scheduled", "confirmed")),
        Appointment.starts_at < ends_at,
        Appointment.ends_at > starts_at,
    )
    if exclude_id is not None:
        query = query.filter(Appointment.id != exclude_id)
    if query.first() is not None:
        raise HTTPException(status_code=409, detail="Nhân viên đã có lịch hẹn trùng thời gian.")


def _appointment_out(db: Session, row: Appointment) -> dict:
    customer = db.query(Customer).filter(Customer.id == row.customer_id, Customer.business_id == row.business_id).first()
    service = db.query(AppointmentService).filter(AppointmentService.id == row.service_id, AppointmentService.business_id == row.business_id).first()
    return {
        "id": row.id,
        "business_id": row.business_id,
        "customer_id": row.customer_id,
        "customer_name": customer.name if customer else None,
        "service_id": row.service_id,
        "service_name": service.name if service else None,
        "service_price": service.price if service else Decimal("0"),
        "assigned_user_id": row.assigned_user_id,
        "starts_at": row.starts_at,
        "ends_at": row.ends_at,
        "status": row.status,
        "notes": row.notes,
        "reminder_minutes_before": row.reminder_minutes_before,
        "send_customer_reminder": row.send_customer_reminder,
        "reminder_at": row.reminder_at,
        "reminder_sent_at": row.reminder_sent_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _enqueue_reminder(db: Session, appointment: Appointment) -> None:
    if appointment.status not in {"scheduled", "confirmed"} or appointment.reminder_at is None or appointment.reminder_sent_at is not None or appointment.starts_at <= _now():
        return
    reminder_at = appointment.reminder_at
    key = f"appointment:{appointment.id}:reminder:{reminder_at.isoformat()}"
    existing = db.query(CrmJob).filter(CrmJob.business_id == appointment.business_id, CrmJob.idempotency_key == key).first()
    if existing is not None and existing.status in {"succeeded", "failed"}:
        existing.status = "pending"
        existing.attempts = 0
        existing.last_error = None
        existing.run_at = max(reminder_at, _now())
    elif existing is None:
        enqueue_job(
            db,
            business_id=appointment.business_id,
            kind="appointment.reminder",
            payload={"appointment_id": appointment.id, "reminder_at": reminder_at.isoformat()},
            idempotency_key=key,
            run_at=max(reminder_at, _now()),
        )


@router.get("/services")
def list_services(
    db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context),
    active_only: bool = False,
):
    query = db.query(AppointmentService).filter(AppointmentService.business_id == tenant.business_id)
    if active_only:
        query = query.filter(AppointmentService.is_active.is_(True))
    return {"items": query.order_by(AppointmentService.is_active.desc(), AppointmentService.name.asc()).all()}


@router.post("/services", status_code=201, dependencies=[Depends(require_write_access)])
def create_service(payload: ServiceCreate, db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context)):
    if not payload.name.strip():
        raise HTTPException(status_code=422, detail="Tên dịch vụ không được để trống.")
    row = AppointmentService(
        business_id=tenant.business_id, name=payload.name.strip(), description=payload.description.strip() if payload.description else None,
        duration_minutes=payload.duration_minutes, price=payload.price,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/services/{service_id}", dependencies=[Depends(require_write_access)])
def update_service(
    service_id: int, payload: ServiceUpdate, db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context),
):
    row = _service(db, service_id, tenant, active=False)
    changes = payload.model_dump(exclude_unset=True)
    if any(key in changes and changes[key] is None for key in ("name", "duration_minutes", "price", "is_active")):
        raise HTTPException(status_code=422, detail="Tên, thời lượng, giá và trạng thái dịch vụ không được để trống.")
    if changes.get("name") is not None and not changes["name"].strip():
        raise HTTPException(status_code=422, detail="Tên dịch vụ không được để trống.")
    for key, value in changes.items():
        setattr(row, key, value.strip() if key in {"name", "description"} and value else value)
    db.commit()
    db.refresh(row)
    return row


@router.get("")
def list_appointments(
    db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context),
    status: AppointmentStatus | None = None,
    starts_from: datetime | None = None,
    starts_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
):
    query = db.query(Appointment).filter(Appointment.business_id == tenant.business_id)
    if status:
        query = query.filter(Appointment.status == status)
    if starts_from:
        query = query.filter(Appointment.starts_at >= _naive_utc(starts_from))
    if starts_to:
        query = query.filter(Appointment.starts_at < _naive_utc(starts_to))
    total = query.count()
    rows = query.order_by(Appointment.starts_at.asc(), Appointment.id.asc()).offset(offset).limit(limit).all()
    return {"items": [_appointment_out(db, row) for row in rows], "total": total}


@router.post("", status_code=201, dependencies=[Depends(require_write_access)])
def create_appointment(
    payload: AppointmentCreate,
    db: Session = Depends(get_tenant_db), user_db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context), platform_db: Session = Depends(get_platform_db),
):
    customer = _customer(db, payload.customer_id, tenant)
    if payload.send_customer_reminder and not customer_email_for_delivery(
        db, business_id=tenant.business_id, customer_id=customer.id,
    ):
        raise HTTPException(status_code=422, detail="Khách hàng chưa có email hợp lệ để nhận nhắc lịch.")
    service = _service(db, payload.service_id, tenant)
    _assignee(user_db, payload.assigned_user_id, tenant)
    starts_at = _naive_utc(payload.starts_at)
    reminder_at = starts_at - timedelta(minutes=payload.reminder_minutes_before) if payload.reminder_minutes_before else None
    ends_at = starts_at + timedelta(minutes=service.duration_minutes)
    _ensure_no_conflict(db, tenant, starts_at, ends_at, payload.assigned_user_id)
    row = Appointment(
        business_id=tenant.business_id, customer_id=customer.id, service_id=service.id,
        assigned_user_id=payload.assigned_user_id, starts_at=starts_at,
        ends_at=ends_at, status="scheduled",
        notes=payload.notes.strip() if payload.notes else None,
        reminder_minutes_before=payload.reminder_minutes_before,
        send_customer_reminder=payload.send_customer_reminder,
        reminder_at=reminder_at,
    )
    db.add(row)
    db.flush()
    _enqueue_reminder(db, row)
    db.commit()
    db.refresh(row)
    emit_workflow_event(db, tenant, "appointment.created", f"appointment:{row.id}:created", {"appointment_id": row.id, "customer_id": row.customer_id, "service_id": row.service_id, "status": row.status}, platform_db=platform_db)
    return _appointment_out(db, row)


@router.patch("/{appointment_id}", dependencies=[Depends(require_write_access)])
def update_appointment(
    appointment_id: int, payload: AppointmentUpdate, db: Session = Depends(get_tenant_db),
    user_db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context), platform_db: Session = Depends(get_platform_db),
):
    row = db.query(Appointment).filter(Appointment.id == appointment_id, Appointment.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Lịch hẹn không tồn tại.")
    previous_status = row.status
    changes = payload.model_dump(exclude_unset=True)
    if any(key in changes and changes[key] is None for key in ("customer_id", "service_id", "status", "reminder_minutes_before", "starts_at")):
        raise HTTPException(status_code=422, detail="Trạng thái, giờ hẹn và thời gian nhắc không được để trống.")
    if "customer_id" in changes and changes["customer_id"] is not None:
        _customer(db, changes["customer_id"], tenant)
    if "service_id" in changes and changes["service_id"] is not None:
        _service(db, changes["service_id"], tenant)
    if "assigned_user_id" in changes:
        _assignee(user_db, changes["assigned_user_id"], tenant)
    if changes.get("send_customer_reminder", row.send_customer_reminder):
        customer_id = changes.get("customer_id", row.customer_id)
        if not customer_email_for_delivery(db, business_id=tenant.business_id, customer_id=customer_id):
            raise HTTPException(status_code=422, detail="Khách hàng chưa có email hợp lệ để nhận nhắc lịch.")
    reschedule = any(key in changes for key in ("starts_at", "service_id", "reminder_minutes_before"))
    for key, value in changes.items():
        if key == "starts_at" and value is not None:
            value = _naive_utc(value)
        if key == "notes" and value:
            value = value.strip()
        setattr(row, key, value)
    if reschedule:
        service = _service(db, row.service_id, tenant, active=False)
        row.ends_at = row.starts_at + timedelta(minutes=service.duration_minutes)
        row.reminder_at = row.starts_at - timedelta(minutes=row.reminder_minutes_before) if row.reminder_minutes_before else None
        row.reminder_sent_at = None
    if row.status in {"scheduled", "confirmed"}:
        _ensure_no_conflict(db, tenant, row.starts_at, row.ends_at, row.assigned_user_id, exclude_id=row.id)
    db.flush()
    _enqueue_reminder(db, row)
    db.commit()
    db.refresh(row)
    if row.status != previous_status:
        emit_workflow_event(db, tenant, "appointment.status_changed", f"appointment:{row.id}:status:{row.status}:{row.updated_at}", {"appointment_id": row.id, "customer_id": row.customer_id, "service_id": row.service_id, "from_status": previous_status, "status": row.status}, platform_db=platform_db)
    return _appointment_out(db, row)
