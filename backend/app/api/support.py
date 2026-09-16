"""Owner-controlled support grants and short-lived support sessions."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.platform_session import get_platform_db
from app.database.tenant_session import tenant_session
from app.models.business import User
from app.models.channel import Channel
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
from app.tenancy.schema import schema_name_for


router = APIRouter()


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
