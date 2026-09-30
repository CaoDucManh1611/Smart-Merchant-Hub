"""Persistence-first notification helpers used by CRM workflows and SLA jobs."""

from email.message import EmailMessage
import logging
import smtplib

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.notification import Notification


logger = logging.getLogger(__name__)


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


def deliver_notification_email(*, recipient_email: str | None, title: str, body: str) -> bool:
    """Deliver a short staff notification when SMTP is configured.

    Notifications are always persisted first.  Email delivery is deliberately
    best-effort so a missing local SMTP configuration never prevents a ticket
    or workflow from completing; the in-app notification remains available.
    """
    recipient = str(recipient_email or "").strip()
    host = str(settings.OTP_SMTP_HOST or "").strip()
    sender = str(settings.OTP_FROM_EMAIL or settings.OTP_SMTP_USERNAME or "").strip()
    if not recipient or not host or not sender:
        return False
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = str(title or "Thông báo CRM").strip()[:255]
    message.set_content(str(body or "").strip()[:10000])
    try:
        with smtplib.SMTP(host, int(settings.OTP_SMTP_PORT), timeout=10) as client:
            client.ehlo()
            if bool(settings.OTP_SMTP_USE_TLS):
                client.starttls()
                client.ehlo()
            username = str(settings.OTP_SMTP_USERNAME or "").strip()
            password = str(settings.OTP_SMTP_PASSWORD or "")
            if username:
                client.login(username, password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        logger.warning("CRM staff notification email failed: error_type=%s", type(error).__name__)
        return False
    return True


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


def create_sla_warning_notification(db: Session, *, business_id: int, ticket_id: int, user_id: int | None, title: str, due_at: str | None = None) -> Notification:
    return create_notification(
        db,
        business_id=business_id,
        user_id=user_id,
        kind="sla_warning",
        title=title,
        body="Ticket sắp chạm hạn SLA và cần được ưu tiên xử lý.",
        metadata={"ticket_id": ticket_id, "sla_due_at": due_at},
    )
