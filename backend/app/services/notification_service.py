"""Persistence-first notification helpers used by CRM workflows and SLA jobs."""

from sqlalchemy.orm import Session

from app.models.notification import Notification


def create_notification(
    db: Session,
    *,
    business_id: int,
    kind: str,
    title: str,
    body: str | None = None,
    user_id: int | None = None,
    metadata: dict | None = None,
) -> Notification:
    """Store a notification before any optional delivery integration runs."""
    notification = Notification(
        business_id=business_id,
        user_id=user_id,
        kind=kind.strip()[:40],
        title=title.strip()[:255],
        body=body,
        metadata_=metadata or {},
    )
    db.add(notification)
    db.flush()
    return notification


def create_sla_notification(db: Session, *, business_id: int, ticket_id: int, user_id: int | None, title: str, due_at: str | None = None) -> Notification:
    return create_notification(
        db,
        business_id=business_id,
        user_id=user_id,
        kind="sla",
        title=title,
        body="Ticket cần được xử lý trước hạn SLA.",
        metadata={"ticket_id": ticket_id, "sla_due_at": due_at},
    )
