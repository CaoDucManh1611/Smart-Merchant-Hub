"""Tenant-scoped controls for the sales chatbot runtime."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_write_access
from app.db.dependencies import get_db
from app.models.business import User
from app.models.canned_response import CannedResponse
from app.models.chatbot import ChatbotConfig
from app.models.conversation import Conversation
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
    FollowUpCreate,
    FollowUpListOut,
    FollowUpOut,
)
from app.services.chatbot_agent import AGENT_TOOLS, build_agent_memory, execute_chatbot_tool
from app.services.chatbot_followup import dispatch_due_followups, schedule_followup
from app.services.audit_service import record_audit
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter()


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
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return _config(db, tenant)


@router.put("/config", response_model=ChatbotConfigOut, dependencies=[Depends(require_write_access)])
def update_config(
    payload: ChatbotConfigUpdate,
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    return _set_bot_mode(db, _conversation(db, conversation_id, tenant), "human", payload.reason if payload else None, actor, tenant)


@router.post("/conversations/{conversation_id}/resume", response_model=BotModeOut, dependencies=[Depends(require_write_access)])
def resume_bot(
    conversation_id: int,
    payload: BotModeRequest | None = None,
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    try:
        result = execute_chatbot_tool(db, tenant.business_id, conversation_id, payload.tool, payload.arguments)
    except ValueError as exc:
        if str(exc) == "tool_not_allowed":
            raise HTTPException(status_code=422, detail="Tool chưa được cho phép.") from exc
        if str(exc) == "conversation_not_found":
            raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại.") from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action="chatbot_tool_executed", resource_type="conversation", resource_id=conversation_id, metadata={"tool": payload.tool})
    db.commit()
    return {"tool": payload.tool, "result": result}


@router.get("/followups", response_model=FollowUpListOut)
def list_followups(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    from app.models.chatbot_followup import ChatbotFollowUp

    query = db.query(ChatbotFollowUp).filter(ChatbotFollowUp.business_id == tenant.business_id)
    if status:
        query = query.filter(ChatbotFollowUp.status == status)
    items = query.order_by(ChatbotFollowUp.run_at.asc(), ChatbotFollowUp.id.asc()).limit(500).all()
    return {"items": items, "total": len(items)}


@router.post("/followups", response_model=FollowUpOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_followup(
    payload: FollowUpCreate,
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
