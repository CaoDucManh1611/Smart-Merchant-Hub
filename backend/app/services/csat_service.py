"""Customer satisfaction surveys for completed support conversations."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.customer_feedback import CustomerFeedback
from app.services.chatbot_followup import schedule_followup
from app.services.notification_service import create_notification


CSAT_MESSAGE = "Shop vừa xử lý xong yêu cầu của bạn. Bạn đánh giá trải nghiệm hỗ trợ từ 1–5 sao nhé (1: chưa tốt, 5: rất tốt)."
CSAT_THANK_YOU = "Cảm ơn bạn đã đánh giá! Phản hồi của bạn giúp shop phục vụ tốt hơn."


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_csat_rating(text: str | None) -> int | None:
    """Parse an explicit 1–5 CSAT answer without treating arbitrary numbers as ratings."""
    value = str(text or "").strip().casefold()
    if not value:
        return None
    direct = re.fullmatch(r"([1-5])(?:\s*(?:sao|/\s*5))?", value)
    if direct:
        return int(direct.group(1))
    mentioned = re.search(r"(?:đánh giá|chấm|rating|sao)[^0-9]{0,12}([1-5])(?:\s*(?:sao|/\s*5))?", value)
    return int(mentioned.group(1)) if mentioned else None


def schedule_csat_survey(
    db: Session,
    *,
    business_id: int,
    conversation_id: int,
    ticket_id: int,
    run_at: datetime | None = None,
) -> CustomerFeedback:
    """Create one durable survey request for a resolved ticket."""
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == business_id,
    ).first()
    if conversation is None:
        raise ValueError("conversation_not_found")
    key = f"ticket:{ticket_id}:csat"
    existing = db.query(CustomerFeedback).filter(
        CustomerFeedback.business_id == business_id,
        CustomerFeedback.idempotency_key == key,
    ).first()
    if existing is not None:
        return existing
    requested_at = run_at or (_now() + timedelta(minutes=1))
    if requested_at.tzinfo is not None:
        requested_at = requested_at.astimezone(timezone.utc).replace(tzinfo=None)
    feedback = CustomerFeedback(
        business_id=business_id,
        conversation_id=conversation_id,
        customer_id=conversation.customer_id,
        ticket_id=ticket_id,
        idempotency_key=key,
        status="scheduled",
        metadata_={"handled_by": "bot" if conversation.bot_mode == "auto" else "human"},
    )
    db.add(feedback)
    db.flush()
    followup = schedule_followup(
        db,
        business_id,
        conversation_id,
        CSAT_MESSAGE,
        requested_at,
        kind="csat",
        metadata={"feedback_id": feedback.id, "ticket_id": ticket_id},
    )
    feedback.followup_id = followup.id
    return feedback


def mark_csat_sent(db: Session, feedback_id: int, business_id: int) -> CustomerFeedback | None:
    feedback = db.query(CustomerFeedback).filter(
        CustomerFeedback.id == feedback_id,
        CustomerFeedback.business_id == business_id,
    ).first()
    if feedback is None:
        return None
    if feedback.status == "scheduled":
        feedback.status = "sent"
    return feedback


def record_csat_response(
    db: Session,
    *,
    business_id: int,
    conversation_id: int,
    rating: int,
    comment: str | None = None,
) -> bool:
    if rating < 1 or rating > 5:
        raise ValueError("rating_invalid")
    feedback = db.query(CustomerFeedback).filter(
        CustomerFeedback.business_id == business_id,
        CustomerFeedback.conversation_id == conversation_id,
        CustomerFeedback.status == "sent",
    ).order_by(CustomerFeedback.requested_at.desc(), CustomerFeedback.id.desc()).first()
    if feedback is None:
        return False
    feedback.rating = rating
    feedback.comment = str(comment or "").strip()[:2000] or None
    feedback.status = "responded"
    feedback.responded_at = _now()
    create_notification(
        db,
        business_id=business_id,
        kind="csat_response",
        title=f"Khách đánh giá hỗ trợ {rating}/5",
        body="Có phản hồi CSAT mới trong Customer 360.",
        metadata={"feedback_id": feedback.id, "conversation_id": conversation_id, "rating": rating},
    )
    db.commit()
    return True


def consume_csat_response(
    db: Session,
    *,
    business_id: int,
    conversation_id: int,
    text: str | None,
) -> bool:
    """Consume a pending survey answer when the inbound text is an explicit rating."""
    rating = parse_csat_rating(text)
    if rating is None:
        return False
    return record_csat_response(
        db,
        business_id=business_id,
        conversation_id=conversation_id,
        rating=rating,
    )


def summarize_csat(db: Session, business_id: int) -> dict:
    rows = db.query(CustomerFeedback).filter(
        CustomerFeedback.business_id == business_id,
        CustomerFeedback.status == "responded",
        CustomerFeedback.rating.is_not(None),
    ).all()
    responses = len(rows)
    if not responses:
        return {"responses": 0, "average_rating": 0.0, "satisfaction_rate": 0.0, "bot_resolution_rate": 0.0}
    average = round(sum(int(row.rating) for row in rows) / responses, 2)
    satisfied = sum(1 for row in rows if int(row.rating) >= 4)
    bot_handled = sum(1 for row in rows if (row.metadata_ or {}).get("handled_by") == "bot")
    return {
        "responses": responses,
        "average_rating": average,
        "satisfaction_rate": round(satisfied / responses, 4),
        "bot_resolution_rate": round(bot_handled / responses, 4),
    }
