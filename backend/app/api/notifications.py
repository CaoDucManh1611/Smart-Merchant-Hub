"""Operational notification inbox for SLA and workflow signals."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_optional_user
from app.db.dependencies import get_db
from app.models.business import User
from app.models.notification import Notification
from app.schemas.notification import NotificationOut
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.auth.dependencies import require_write_access


router = APIRouter()


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    user: User | None = Depends(get_optional_user),
):
    # Development-header callers can still see tenant-wide notifications;
    # authenticated callers are narrowed to their own plus broadcast rows.
    query = db.query(Notification).filter(Notification.business_id == tenant.business_id)
    if user is not None:
        query = query.filter((Notification.user_id == user.id) | Notification.user_id.is_(None))
    return query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(100).all()


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut, dependencies=[Depends(require_write_access)])
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    row = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.business_id == tenant.business_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Notification không tồn tại.")
    row.is_read = True
    db.commit()
    db.refresh(row)
    return row
