"""Assign bookings only to shop staff with a live authenticated CRM socket."""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.models.business import User
from app.models.industry_modules import Appointment

logger = logging.getLogger(__name__)


def presence_store():
    from redis import Redis
    from app.core.config import settings
    if not settings.REDIS_URL:
        raise RuntimeError("Shared presence is not configured")
    return Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)


def presence_key(business_id):
    return f"smh:staff-presence:{int(business_id)}"


def choose_assignee(db, business_id, starts_at, ends_at, *, user_db=None):
    from app.db.database import SessionLocal
    import time
    try:
        online = [int(value) for value in presence_store().zrangebyscore(
            presence_key(business_id), time.time() - 75, "+inf")]
    except Exception:
        logger.warning("Staff presence unavailable; appointment remains unassigned")
        return None
    if not online:
        return None
    owned = user_db is None
    identities = user_db or SessionLocal()
    try:
        staff = identities.query(User.id).filter(
            User.business_id == business_id, User.is_active.is_(True), User.id.in_(online),
            User.role.in_(("business_agent", "business_admin", "shop_agent", "shop_admin",
                          "agent", "admin", "owner", "sales", "sales_agent", "sales_staff",
                          "support", "customer_support", "support_agent", "cskh")),
        ).all()
        for (user_id,) in sorted(staff):
            if db.get_bind().dialect.name == "postgresql":
                from sqlalchemy import text
                db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                           {"key": f"appointment:{business_id}:{user_id}"})
            conflict = db.query(Appointment.id).filter(
                Appointment.business_id == business_id, Appointment.assigned_user_id == user_id,
                Appointment.status.in_(("pending", "scheduled", "confirmed")),
                Appointment.starts_at < ends_at, Appointment.ends_at > starts_at,
            ).first()
            if conflict is None:
                return user_id
        return None
    finally:
        if owned:
            identities.close()


def booking_notes(request_id, definitions, values, timezone_name):
    from app.services.business_request import PAYMENT_LABELS
    lines = [f"Yêu cầu đặt lịch từ chatbot #{request_id} — Chờ nhân viên xác nhận"]
    for field in definitions:
        value = values.get(field["key"], "")
        if field["type"] == "datetime" and value:
            value = datetime.fromisoformat(value).astimezone(ZoneInfo(timezone_name)).strftime("%d/%m/%Y %H:%M")
        elif field["key"] == "payment_method":
            value = PAYMENT_LABELS.get(value, value)
        lines.append(f"{field['label']}: {value}")
    return "\n".join(lines)
