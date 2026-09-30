"""Tenant-scoped controls for the sales chatbot runtime."""

import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_write_access
from app.database.platform_session import get_platform_db
from app.tenancy.crm_session import get_tenant_db
from app.models.business import User
from app.models.canned_response import CannedResponse
from app.models.chatbot import ChatbotConfig
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.audit_log import AuditLog
from app.schemas.chatbot import (
    BotModeOut,
    BotModeRequest,
    CannedResponseCreate,
    CannedResponseListOut,
    CannedResponseOut,
    CannedResponseUpdate,
    ChatbotConfigOut,
    ChatbotConfigUpdate,
    ChatbotToolRequest,
    ChatbotToolResponse,
    CustomerFeedbackListOut,
    CustomerFeedbackOut,
    CsatSummaryOut,
    ChatbotResponseFeedbackRequest,
    ChatbotResponseFeedbackOut,
    LearningSummaryOut,
    TopicDiscoveryOut,
    FollowUpCreate,
    FollowUpListOut,
    FollowUpOut,
)
from app.services.chatbot_agent import AGENT_TOOLS, build_agent_memory, execute_chatbot_tool
from app.services.chatbot_followup import dispatch_due_followups, schedule_followup, schedule_inactive_customer_followups
from app.services.csat_service import summarize_csat
from app.services.audit_service import record_audit
from app.services.topic_discovery_service import tenant_topic_suggestions
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter()


_LEARNING_TOPICS = (
    ("pricing", "Giá và sản phẩm", ("giá", "bao nhiêu", "chi phí", "sản phẩm", "mẫu", "size", "màu")),
    ("order_delivery", "Đơn hàng và giao hàng", ("đơn", "đặt", "mua", "giao", "ship", "vận chuyển", "cod", "thanh toán")),
    ("returns_warranty", "Đổi trả và bảo hành", ("đổi", "trả", "hoàn", "bảo hành", "lỗi", "hỏng", "bảo đảm")),
    ("support_complaint", "Hỗ trợ và khiếu nại", ("khiếu nại", "phàn nàn", "không hài lòng", "hỗ trợ", "giúp", "lỗi hệ thống")),
)


def _searchable_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFD", str(value or "").lower())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _topic_for_message(content: str | None) -> tuple[str, str]:
    text = _searchable_text(content)
    best_key, best_label, best_score = "other", "Nhu cầu khác", 0
    for key, label, keywords in _LEARNING_TOPICS:
        score = sum(1 for keyword in keywords if _searchable_text(keyword) in text)
        if score > best_score:
            best_key, best_label, best_score = key, label, score
    return best_key, best_label


def _config(db: Session, tenant: TenantContext) -> ChatbotConfig:
    row = db.query(ChatbotConfig).filter(ChatbotConfig.business_id == tenant.business_id).first()
    if row is None:
        row = ChatbotConfig(business_id=tenant.business_id)
        db.add(row)
        db.flush()
    return row


def _conversation(db: Session, conversation_id: int, tenant: TenantContext) -> Conversation:
    row = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == tenant.business_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Cuộc hội thoại không thuộc shop này.")
    return row


@router.get("/config", response_model=ChatbotConfigOut)
def get_config(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return _config(db, tenant)


@router.put("/config", response_model=ChatbotConfigOut, dependencies=[Depends(require_write_access)])
def update_config(
    payload: ChatbotConfigUpdate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    row = _config(db, tenant)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="chatbot_config_updated",
        resource_type="chatbot_config",
        resource_id=row.id,
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/canned-responses", response_model=CannedResponseListOut)
def list_canned_responses(
    enabled: bool | None = Query(default=None),
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    query = db.query(CannedResponse).filter(CannedResponse.business_id == tenant.business_id)
    if enabled is not None:
        query = query.filter(CannedResponse.enabled.is_(enabled))
    items = query.order_by(CannedResponse.title.asc(), CannedResponse.id.asc()).all()
    return {"items": items, "total": len(items)}


@router.post("/canned-responses", response_model=CannedResponseOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_canned_response(
    payload: CannedResponseCreate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    row = CannedResponse(business_id=tenant.business_id, **payload.model_dump())
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Shortcut đã tồn tại trong shop.") from exc
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="canned_response_created",
        resource_type="canned_response",
        resource_id=row.id,
    )
    db.commit()
    db.refresh(row)
    return row


@router.patch("/canned-responses/{response_id}", response_model=CannedResponseOut, dependencies=[Depends(require_write_access)])
def update_canned_response(
    response_id: int,
    payload: CannedResponseUpdate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    row = db.query(CannedResponse).filter(
        CannedResponse.id == response_id,
        CannedResponse.business_id == tenant.business_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Mẫu trả lời không tồn tại.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Shortcut đã tồn tại trong shop.") from exc
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action="canned_response_updated", resource_type="canned_response", resource_id=row.id)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/canned-responses/{response_id}", status_code=204, dependencies=[Depends(require_write_access)])
def delete_canned_response(
    response_id: int,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    row = db.query(CannedResponse).filter(
        CannedResponse.id == response_id,
        CannedResponse.business_id == tenant.business_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Mẫu trả lời không tồn tại.")
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action="canned_response_deleted", resource_type="canned_response", resource_id=row.id)
    db.delete(row)
    db.commit()


def _set_bot_mode(db: Session, conversation: Conversation, mode: str, reason: str | None, actor: User | None, tenant: TenantContext):
    previous = conversation.bot_mode
    conversation.bot_mode = mode
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="chatbot_human" if mode == "human" else "chatbot_auto",
        resource_type="conversation",
        resource_id=conversation.id,
        metadata={"from": previous, "to": mode, "reason": reason},
    )
    db.commit()
    return BotModeOut(conversation_id=conversation.id, bot_mode=mode, reason=reason)


@router.post("/conversations/{conversation_id}/pause", response_model=BotModeOut, dependencies=[Depends(require_write_access)])
def pause_bot(
    conversation_id: int,
    payload: BotModeRequest | None = None,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    return _set_bot_mode(db, _conversation(db, conversation_id, tenant), "human", payload.reason if payload else None, actor, tenant)


@router.post("/conversations/{conversation_id}/resume", response_model=BotModeOut, dependencies=[Depends(require_write_access)])
def resume_bot(
    conversation_id: int,
    payload: BotModeRequest | None = None,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    return _set_bot_mode(db, _conversation(db, conversation_id, tenant), "auto", payload.reason if payload else None, actor, tenant)


@router.get("/tools")
def list_tools():
    """Return the allow-list exposed to an agent model."""
    return {"items": [{"name": name, "description": description} for name, description in AGENT_TOOLS.items()]}


@router.get("/conversations/{conversation_id}/memory")
def get_memory(
    conversation_id: int,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    try:
        return build_agent_memory(db, tenant.business_id, conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại.") from exc


@router.post("/conversations/{conversation_id}/tools/execute", response_model=ChatbotToolResponse, dependencies=[Depends(require_write_access)])
def execute_tool(
    conversation_id: int,
    payload: ChatbotToolRequest,
    db: Session = Depends(get_tenant_db),
    platform_db: Session = Depends(get_platform_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    try:
        result = execute_chatbot_tool(
            db,
            tenant.business_id,
            conversation_id,
            payload.tool,
            payload.arguments,
            platform_db=platform_db,
        )
    except ValueError as exc:
        if str(exc) == "tool_not_allowed":
            raise HTTPException(status_code=422, detail="Tool chưa được cho phép.") from exc
        if str(exc) == "conversation_not_found":
            raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại.") from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        actor_type="bot" if actor is None else "staff",
        action="chatbot_tool_executed",
        resource_type="conversation",
        resource_id=conversation_id,
        correlation_id=payload.correlation_id,
        metadata={"tool": payload.tool},
    )
    db.commit()
    return {"tool": payload.tool, "result": result}


@router.get("/followups", response_model=FollowUpListOut)
def list_followups(
    status: str | None = Query(default=None),
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    from app.models.chatbot_followup import ChatbotFollowUp

    query = db.query(ChatbotFollowUp).filter(ChatbotFollowUp.business_id == tenant.business_id)
    if status:
        query = query.filter(ChatbotFollowUp.status == status)
    items = query.order_by(ChatbotFollowUp.run_at.asc(), ChatbotFollowUp.id.asc()).limit(500).all()
    return {"items": items, "total": len(items)}


@router.post("/proactive/inactive-customers", dependencies=[Depends(require_write_access)])
def schedule_inactive_customers(
    inactive_days: int = Query(default=30, ge=7, le=3650),
    run_in_minutes: int = Query(default=5, ge=0, le=1440),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    result = schedule_inactive_customer_followups(
        db,
        business_id=tenant.business_id,
        inactive_days=inactive_days,
        run_at=datetime.now(timezone.utc) + timedelta(minutes=run_in_minutes),
        limit=limit,
    )
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="proactive_inactive_customers_scheduled",
        resource_type="chatbot_followup",
        metadata={"inactive_days": inactive_days, "scheduled": result["scheduled"], "skipped": result["skipped"]},
    )
    db.commit()
    return result


@router.get("/csat", response_model=CustomerFeedbackListOut)
def list_csat_feedback(
    status: str | None = Query(default=None),
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    from app.models.customer_feedback import CustomerFeedback

    query = db.query(CustomerFeedback).filter(CustomerFeedback.business_id == tenant.business_id)
    if status:
        query = query.filter(CustomerFeedback.status == status)
    items = query.order_by(CustomerFeedback.requested_at.desc(), CustomerFeedback.id.desc()).limit(500).all()
    return {
        "items": items,
        "total": len(items),
        "summary": summarize_csat(db, tenant.business_id),
    }


def _learning_summary(db: Session, business_id: int, days: int) -> dict:
    """Build transparent learning signals without training a model in-request.

    Topic grouping is deliberately deterministic and explainable.  It gives a
    shop useful unsupervised-style discovery immediately, while the stored
    response ratings become safe reward data for a later bandit/model job.
    """

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    rows = db.query(Message).join(
        Conversation, Conversation.id == Message.conversation_id,
    ).filter(
        Conversation.business_id == business_id,
        Message.direction == "inbound",
        Message.received_at >= since,
    ).order_by(Message.received_at.desc(), Message.id.desc()).limit(2000).all()

    buckets: dict[str, dict] = defaultdict(lambda: {"label": "Nhu cầu khác", "messages": 0, "conversations": set(), "examples": []})
    for message in rows:
        if not str(message.content or "").strip():
            continue
        key, label = _topic_for_message(message.content)
        bucket = buckets[key]
        bucket["label"] = label
        bucket["messages"] += 1
        bucket["conversations"].add(int(message.conversation_id))
        if len(bucket["examples"]) < 3:
            bucket["examples"].append(str(message.content).strip()[:160])

    feedback_rows = db.query(AuditLog).filter(
        AuditLog.business_id == business_id,
        AuditLog.action == "chatbot_response_feedback",
        AuditLog.created_at >= since,
    ).all()
    positive = sum(1 for row in feedback_rows if int((row.metadata_ or {}).get("rating", 0)) > 0)
    negative = sum(1 for row in feedback_rows if int((row.metadata_ or {}).get("rating", 0)) < 0)
    total_feedback = positive + negative
    feedback = {
        "total": total_feedback,
        "positive": positive,
        "negative": negative,
        "positive_rate": round(positive / total_feedback, 4) if total_feedback else 0.0,
    }
    topics = [
        {
            "key": key,
            "label": value["label"],
            "message_count": value["messages"],
            "conversation_count": len(value["conversations"]),
            "examples": value["examples"],
        }
        for key, value in sorted(buckets.items(), key=lambda item: item[1]["messages"], reverse=True)
        if value["messages"]
    ]
    return {
        "period_days": days,
        "inbound_messages": sum(item["message_count"] for item in topics),
        "conversations_sampled": len({int(message.conversation_id) for message in rows}),
        "topics": topics,
        "response_feedback": feedback,
        "method": "Phân nhóm minh bạch theo nội dung; phản hồi được lưu làm tín hiệu thưởng",
    }


@router.get("/learning/summary", response_model=LearningSummaryOut)
def learning_summary(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return _learning_summary(db, tenant.business_id, int(days))


@router.get("/learning/topic-suggestions", response_model=TopicDiscoveryOut)
def topic_suggestions(
    days: int = Query(default=30, ge=1, le=365),
    max_messages: int = Query(default=2000, ge=10, le=5000),
    max_topics: int = Query(default=12, ge=1, le=30),
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Return tenant-local, read-only topic candidates for admin review."""

    return tenant_topic_suggestions(
        db,
        tenant.business_id,
        days=int(days),
        max_messages=int(max_messages),
        max_topics=int(max_topics),
    )


@router.post("/messages/{message_id}/feedback", response_model=ChatbotResponseFeedbackOut, dependencies=[Depends(require_write_access)])
def record_response_feedback(
    message_id: int,
    payload: ChatbotResponseFeedbackRequest,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    message = db.query(Message).join(
        Conversation, Conversation.id == Message.conversation_id,
    ).filter(
        Message.id == message_id,
        Conversation.business_id == tenant.business_id,
    ).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Tin nhắn không thuộc shop này.")
    if message.direction != "outbound" or message.sender_type != "bot":
        raise HTTPException(status_code=422, detail="Chỉ có thể đánh giá câu trả lời của trợ lý.")

    correlation_id = payload.idempotency_key or f"bot-feedback:{tenant.business_id}:{message_id}:{actor.id if actor else 'system'}"
    existing = db.query(AuditLog).filter(
        AuditLog.business_id == tenant.business_id,
        AuditLog.action == "chatbot_response_feedback",
        AuditLog.correlation_id == correlation_id,
    ).first()
    if existing is not None:
        # Backfill the reward for feedback rows created before the runtime
        # bandit bridge was enabled. The helper is tenant-scoped and
        # idempotent per outbound message.
        from app.services.chatbot_bandit_service import record_message_feedback_reward

        record_message_feedback_reward(
            db,
            business_id=tenant.business_id,
            message=message,
            rating=int((existing.metadata_ or {}).get("rating", payload.rating)),
        )
        db.commit()
        return {"message_id": message_id, "rating": int((existing.metadata_ or {}).get("rating", payload.rating)), "recorded": True}

    from app.services.chatbot_bandit_service import record_message_feedback_reward

    decision = record_message_feedback_reward(
        db,
        business_id=tenant.business_id,
        message=message,
        rating=payload.rating,
    )

    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="chatbot_response_feedback",
        resource_type="message",
        resource_id=message_id,
        correlation_id=correlation_id,
        metadata={
            "rating": payload.rating,
            "comment": payload.comment,
            "conversation_id": message.conversation_id,
            "bandit_decision_id": decision.id if decision is not None else None,
            "bandit_reward": float(decision.reward) if decision is not None and decision.reward is not None else None,
        },
    )
    db.commit()
    return {"message_id": message_id, "rating": payload.rating, "recorded": True}


@router.post("/followups", response_model=FollowUpOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_followup(
    payload: FollowUpCreate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    try:
        row = schedule_followup(
            db,
            tenant.business_id,
            payload.conversation_id,
            payload.message,
            payload.run_at,
            kind=payload.kind,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if str(exc) == "conversation_not_found" else 422, detail=str(exc)) from exc
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action="followup_scheduled", resource_type="chatbot_followup", resource_id=row.id, metadata={"kind": row.kind})
    db.commit()
    db.refresh(row)
    return row


@router.post("/followups/dispatch", dependencies=[Depends(require_write_access)])
def dispatch_followups(
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    result = dispatch_due_followups(db, tenant.business_id, limit=limit)
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action="followups_dispatched", resource_type="chatbot_followup", metadata=result)
    db.commit()
    return result


@router.post("/followups/{followup_id}/cancel", response_model=FollowUpOut, dependencies=[Depends(require_write_access)])
def cancel_followup(
    followup_id: int,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    from app.models.chatbot_followup import ChatbotFollowUp

    row = db.query(ChatbotFollowUp).filter(ChatbotFollowUp.id == followup_id, ChatbotFollowUp.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Follow-up không tồn tại.")
    if row.status == "scheduled":
        row.status = "cancelled"
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action="followup_cancelled", resource_type="chatbot_followup", resource_id=row.id)
    db.commit()
    db.refresh(row)
    return row
