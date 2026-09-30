"""Owner-controlled support grants and short-lived support sessions."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.platform_session import get_platform_db
from app.database.tenant_session import tenant_session
from app.models.business import User
from app.models.channel import Channel, ChannelEvent
from app.models.crm_job import CrmJob
from app.models.platform_control import SupportGrant
from app.schemas.support import (
    SupportGrantCreate,
    SupportGrantOut,
    SupportSessionCreate,
    SupportSessionOut,
)
from app.services.support_access import (
    create_support_grant,
    issue_support_token,
    revoke_support_grant,
    validate_support_token,
)
from app.services.channel_event_service import (
    ingest_normalized_events,
    mark_channel_event_failed,
    mark_channel_event_processed,
    normalize_stored_channel_event,
)
from app.services.message_service import process_and_save_message
from app.services.realtime import manager
from app.tenancy.schema import schema_name_for


router = APIRouter()
logger = logging.getLogger(__name__)


def _support_error(db: Session, exc: Exception) -> HTTPException:
    # Persist the audit row created for denied decisions before returning.
    db.commit()
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=400, detail="Không thể xử lý quyền hỗ trợ.")


@router.post("/support/grants", response_model=SupportGrantOut, status_code=201)
def create_grant(
    payload: SupportGrantCreate,
    actor: User = Depends(get_current_user),
    platform_db: Session = Depends(get_platform_db),
):
    if actor.business_id is None:
        raise HTTPException(status_code=403, detail="Tài khoản này không thuộc shop.")
    try:
        grant = create_support_grant(
            platform_db,
            business_id=int(actor.business_id),
            granted_by_user_id=int(actor.id),
            support_user_id=payload.support_user_id,
            reason=payload.reason,
            scopes=payload.scopes,
            expires_at=payload.expires_at,
        )
        platform_db.commit()
        platform_db.refresh(grant)
        return grant
    except (PermissionError, LookupError, ValueError) as exc:
        raise _support_error(platform_db, exc) from exc


@router.post("/support/grants/{grant_id}/revoke", response_model=SupportGrantOut)
def revoke_grant(
    grant_id: int,
    actor: User = Depends(get_current_user),
    platform_db: Session = Depends(get_platform_db),
):
    try:
        grant = revoke_support_grant(
            platform_db,
            grant_id=grant_id,
            actor_user_id=int(actor.id),
        )
        platform_db.commit()
        platform_db.refresh(grant)
        return grant
    except (PermissionError, LookupError, ValueError) as exc:
        raise _support_error(platform_db, exc) from exc


@router.post("/platform/support-sessions", response_model=SupportSessionOut)
def create_support_session(
    payload: SupportSessionCreate,
    actor: User = Depends(get_current_user),
    platform_db: Session = Depends(get_platform_db),
):
    # Support sessions are an elevated path and always require a verified
    # second factor, even when the ordinary login account has MFA disabled.
    if str(getattr(actor, "mfa_status", "disabled") or "disabled").lower() != "enabled":
        raise HTTPException(
            status_code=403,
            detail={"code": "mfa_required", "message": "Cần bật và xác thực MFA trước khi mở phiên hỗ trợ."},
        )
    try:
        token, expires_at = issue_support_token(
            platform_db,
            grant_id=payload.grant_id,
            support_user_id=int(actor.id),
        )
        grant = platform_db.get(SupportGrant, payload.grant_id)
        if grant is None:
            raise LookupError("Quyền hỗ trợ không tồn tại.")
        platform_db.commit()
        return SupportSessionOut(
            access_token=token,
            grant_id=grant.id,
            business_id=grant.business_id,
            scopes=list(grant.scopes or []),
            expires_at=expires_at,
        )
    except (PermissionError, LookupError, ValueError) as exc:
        raise _support_error(platform_db, exc) from exc


def _support_scope(scope: str):
    def dependency(
        authorization: str | None = Header(default=None),
        platform_db: Session = Depends(get_platform_db),
    ):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Yêu cầu support token.")
        try:
            session = validate_support_token(
                platform_db,
                token=authorization[7:].strip(),
                scope=scope,
            )
            platform_db.commit()
            return session
        except (PermissionError, LookupError, ValueError) as exc:
            raise _support_error(platform_db, exc) from exc

    return dependency


@router.get("/support/health")
def support_health(session=Depends(_support_scope("settings:read"))):
    return {"business_id": session.business_id, "status": "ok", "scope": "settings:read"}


@router.post("/support/channels/{channel_id}/diagnose")
def diagnose_channel(channel_id: int, session=Depends(_support_scope("channels:diagnose"))):
    with tenant_session(schema_name_for(session.business_id)) as tenant_db:
        channel = tenant_db.query(Channel).filter(Channel.id == channel_id).first()
        if channel is None:
            raise HTTPException(status_code=404, detail="Kênh không tồn tại.")
        return {
            "business_id": session.business_id,
            "channel_id": channel.id,
            "status": channel.status,
            "channel_type": channel.channel_type,
        }


@router.post("/support/channel-events/{event_id}/retry")
async def retry_channel_event(event_id: int, session=Depends(_support_scope("channels:retry"))):
    """Replay one failed inbound event inside its owner-approved shop scope."""
    with tenant_session(schema_name_for(session.business_id)) as tenant_db:
        stored_event = (
            tenant_db.query(ChannelEvent)
            .join(Channel, Channel.id == ChannelEvent.channel_id)
            .filter(
                ChannelEvent.id == event_id,
                Channel.business_id == session.business_id,
            )
            .first()
        )
        if stored_event is None:
            raise HTTPException(status_code=404, detail="Sự kiện kênh không tồn tại.")
        if stored_event.status != "failed":
            raise HTTPException(status_code=409, detail="Chỉ có thể thử lại sự kiện đang thất bại.")
        channel = stored_event.channel
        if channel.status != "active":
            raise HTTPException(status_code=409, detail="Kênh không hoạt động, chưa thể thử lại.")

        try:
            normalized = normalize_stored_channel_event(channel, stored_event)
        except (ValueError, TypeError, KeyError):
            raise HTTPException(status_code=409, detail="Payload sự kiện không hợp lệ để thử lại.") from None

        accepted = ingest_normalized_events(tenant_db, [normalized])
        if len(accepted) != 1:
            raise HTTPException(status_code=409, detail="Sự kiện đã được xử lý hoặc đang được thử lại.")
        event = accepted[0]

        try:
            created_messages = []
            for item in event.messages:
                profile = item.metadata or {}
                saved = process_and_save_message(db=tenant_db, message={
                    "channel": event.provider.value,
                    "external_account_id": event.external_account_id,
                    "external_user_id": item.sender_external_id,
                    "external_message_id": item.external_message_id,
                    "content": item.text,
                    "name": profile.get("display_name"),
                    "display_name": profile.get("display_name"),
                    "username": profile.get("username"),
                    "avatar_url": profile.get("avatar_url"),
                    "media_type": item.message_type.value,
                    "media_url": item.attachments[0].url if item.attachments else None,
                    "attachments": [attachment.model_dump(mode="json") for attachment in item.attachments],
                    "raw_payload": event.raw_payload,
                    "business_id": event.business_id,
                    "channel_id": event.channel_id,
                })
                if not isinstance(saved, dict):
                    raise RuntimeError("message_persistence_failed")
                if saved.get("_created", True):
                    created_messages.append(saved)
            mark_channel_event_processed(tenant_db, event)
        except Exception as exc:  # noqa: BLE001
            tenant_db.rollback()
            mark_channel_event_failed(tenant_db, event, exc)
            logger.error(
                "Channel event replay failed: provider=%s event_id=%s error_type=%s",
                event.provider.value,
                stored_event.id,
                type(exc).__name__,
            )
            raise HTTPException(status_code=502, detail="Không thể xử lý lại sự kiện kênh.") from exc

        for saved in created_messages:
            try:
                await manager.broadcast({
                    "type": "message_created",
                    "conversation_id": saved.get("conversation_id"),
                    "message": {key: value for key, value in saved.items() if key != "_created"},
                }, business_id=int(saved.get("business_id") or event.business_id))
            except Exception as exc:  # noqa: BLE001 - persistence already succeeded; do not make a retry duplicate it
                logger.warning("Channel event replay broadcast failed: error_type=%s", type(exc).__name__)

        return {
            "event_id": stored_event.id,
            "status": "processed",
            "messages_created": len(created_messages),
        }


@router.post("/support/jobs/{job_id}/retry")
def retry_job(job_id: int, session=Depends(_support_scope("jobs:retry"))):
    with tenant_session(schema_name_for(session.business_id)) as tenant_db:
        job = tenant_db.get(CrmJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job không tồn tại.")
        if job.status == "succeeded":
            raise HTTPException(status_code=409, detail="Job đã hoàn tất, không thể chạy lại.")
        job.status = "pending"
        job.run_at = datetime.now(timezone.utc).replace(tzinfo=None)
        job.locked_at = None
        job.last_error = None
        tenant_db.commit()
        return {"business_id": session.business_id, "job_id": job.id, "queued": True}
