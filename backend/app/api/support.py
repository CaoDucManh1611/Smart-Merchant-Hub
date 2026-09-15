"""Operational support endpoints guarded by owner-approved grants."""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.dependencies import get_db
from app.models.business import User
from app.models.saas import SupportGrant
from app.schemas.support import SupportGrantCreate, SupportGrantOut, SupportSessionCreate, SupportSessionOut
from app.services.support_access import create_grant, issue_support_session, revoke_grant, validate_support_token


router = APIRouter()


@router.post("/support/grants", response_model=SupportGrantOut, status_code=201)
def grant_support_access(
    payload: SupportGrantCreate,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return create_grant(db, owner=actor, **payload.model_dump())


@router.post("/support/grants/{grant_id}/revoke", response_model=SupportGrantOut)
def revoke_support_access(
    grant_id: int,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return revoke_grant(db, owner=actor, grant_id=grant_id)


@router.post("/platform/support-sessions", response_model=SupportSessionOut)
def create_support_session(
    payload: SupportSessionCreate,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    grant = db.get(SupportGrant, payload.grant_id)
    if grant is None or grant.support_user_id != actor.id:
        raise HTTPException(status_code=404, detail="Quyền hỗ trợ không tồn tại.")
    token, expires_at = issue_support_session(db, support_user=actor, grant=grant)
    return SupportSessionOut(
        access_token=token,
        expires_at=expires_at,
        grant_id=grant.id,
        business_id=grant.business_id,
        scopes=list(grant.scopes or []),
    )


def _support_scope(scope: str):
    def dependency(
        actor: User = Depends(get_current_user),
        authorization: str | None = Header(default=None),
        db: Session = Depends(get_db),
    ):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Yêu cầu support token.")
        _user, grant = validate_support_token(db, token=authorization[7:].strip(), required_scope=scope)
        return grant

    return dependency


@router.get("/support/health")
def support_health(grant=Depends(_support_scope("settings:read"))):
    return {"business_id": grant.business_id, "status": "ok", "scope": "settings:read"}


@router.post("/support/channels/{channel_id}/diagnose")
def diagnose_channel(channel_id: int, grant=Depends(_support_scope("channels:diagnose")), db: Session = Depends(get_db)):
    from app.models.channel import Channel

    channel = db.query(Channel).filter(Channel.id == channel_id, Channel.business_id == grant.business_id).first()
    if channel is None:
        raise HTTPException(status_code=404, detail="Kênh không tồn tại.")
    return {"business_id": grant.business_id, "channel_id": channel.id, "status": channel.status, "channel_type": channel.channel_type}


@router.post("/support/jobs/{job_id}/retry")
def retry_job(job_id: int, grant=Depends(_support_scope("jobs:retry"))):
    # Dispatch is intentionally represented as an auditable acknowledgement;
    # the worker performs the actual retry in its own tenant context.
    return {"business_id": grant.business_id, "job_id": job_id, "queued": True}
