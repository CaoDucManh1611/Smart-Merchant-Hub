"""Owner-controlled, least-privilege support sessions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import decode_token_payload, issue_token, token_hash
from app.models.auth_session import AuthSession
from app.models.business import User
from app.models.saas import SupportGrant
from app.services.audit_service import record_audit


ALLOWED_SCOPES = frozenset({"settings:read", "channels:diagnose", "jobs:retry"})
SUPPORT_TTL_SECONDS = 15 * 60


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_grant(
    db: Session,
    *,
    owner: User,
    support_user_id: int,
    reason: str,
    scopes: list[str],
    expires_at: datetime,
) -> SupportGrant:
    if owner.role != "owner":
        raise HTTPException(status_code=403, detail="Chỉ chủ shop mới được cấp quyền hỗ trợ.")
    reason = str(reason or "").strip()
    normalized_scopes = [str(scope).strip().lower() for scope in scopes]
    if len(reason) < 8:
        raise HTTPException(status_code=422, detail="Lý do hỗ trợ phải có ít nhất 8 ký tự.")
    if not normalized_scopes or len(set(normalized_scopes)) != len(normalized_scopes) or not set(normalized_scopes) <= ALLOWED_SCOPES:
        raise HTTPException(status_code=422, detail="Scope hỗ trợ không hợp lệ.")
    if expires_at.tzinfo is not None:
        expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
    if expires_at <= _now() or expires_at > _now() + timedelta(hours=24):
        raise HTTPException(status_code=422, detail="Thời hạn hỗ trợ phải ở tương lai và tối đa 24 giờ.")
    support_user = db.get(User, support_user_id)
    if support_user is None or not support_user.is_active or support_user.role not in {"support", "platform_support"}:
        raise HTTPException(status_code=422, detail="Support user không hợp lệ.")
    if support_user.business_id != owner.business_id:
        raise HTTPException(status_code=422, detail="Support user phải thuộc cùng shop.")

    grant = SupportGrant(
        business_id=owner.business_id,
        granted_by_user_id=owner.id,
        support_user_id=support_user.id,
        reason=reason,
        scopes=normalized_scopes,
        expires_at=expires_at,
    )
    db.add(grant)
    db.flush()
    record_audit(
        db,
        business_id=owner.business_id,
        user_id=owner.id,
        actor_type="staff",
        action="support_grant_created",
        resource_type="support_grant",
        resource_id=grant.id,
        metadata={"support_user_id": support_user.id, "scopes": normalized_scopes, "expires_at": expires_at.isoformat()},
    )
    db.commit()
    db.refresh(grant)
    return grant


def revoke_grant(db: Session, *, owner: User, grant_id: int) -> SupportGrant:
    grant = db.get(SupportGrant, grant_id)
    if grant is None or grant.business_id != owner.business_id:
        raise HTTPException(status_code=404, detail="Quyền hỗ trợ không tồn tại.")
    if owner.role != "owner":
        raise HTTPException(status_code=403, detail="Chỉ chủ shop mới được thu hồi quyền hỗ trợ.")
    if grant.revoked_at is None:
        grant.revoked_at = _now()
        record_audit(
            db,
            business_id=owner.business_id,
            user_id=owner.id,
            actor_type="staff",
            action="support_grant_revoked",
            resource_type="support_grant",
            resource_id=grant.id,
        )
        db.commit()
        db.refresh(grant)
    return grant


def validate_support_token(db: Session, *, token: str, required_scope: str) -> tuple[User, SupportGrant]:
    """Validate token signature, persisted session, grant and exact scope."""

    try:
        payload = decode_token_payload(token)
        grant_id = int(payload.get("support_grant_id", 0))
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Support token không hợp lệ.") from None
    if not grant_id or required_scope not in set(payload.get("support_scopes") or []):
        raise HTTPException(status_code=403, detail="Support token không có scope yêu cầu.")
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token), AuthSession.revoked_at.is_(None)))
    if session is None or session.expires_at <= _now() or session.user_id != user_id:
        raise HTTPException(status_code=401, detail="Support session không còn hiệu lực.")
    user = db.get(User, user_id)
    grant = db.get(SupportGrant, grant_id)
    if user is None or grant is None or user.role not in {"support", "platform_support"}:
        raise HTTPException(status_code=403, detail="Support identity không hợp lệ.")
    if grant.support_user_id != user.id or grant.business_id != user.business_id:
        raise HTTPException(status_code=403, detail="Support grant không khớp tenant.")
    if grant.revoked_at is not None or grant.expires_at <= _now():
        raise HTTPException(status_code=403, detail="Support grant đã hết hạn hoặc bị thu hồi.")
    if required_scope not in set(grant.scopes or []):
        raise HTTPException(status_code=403, detail="Support grant không có scope yêu cầu.")
    return user, grant


def issue_support_session(db: Session, *, support_user: User, grant: SupportGrant) -> tuple[str, datetime]:
    if grant.support_user_id != support_user.id or grant.revoked_at is not None or grant.expires_at <= _now():
        raise HTTPException(status_code=403, detail="Support grant đã hết hạn hoặc không thuộc tài khoản này.")
    expiry = min(grant.expires_at, _now() + timedelta(seconds=SUPPORT_TTL_SECONDS))
    ttl = max(1, int((expiry - _now()).total_seconds()))
    token, _ = issue_token(
        support_user.id,
        business_id=support_user.business_id,
        role=support_user.role,
        ttl_seconds=ttl,
        extra_claims={"support_grant_id": grant.id, "support_scopes": list(grant.scopes or [])},
    )
    db.add(AuthSession(user_id=support_user.id, token_hash=token_hash(token), expires_at=expiry, device_label="support-session", mfa_verified=True))
    record_audit(
        db,
        business_id=grant.business_id,
        user_id=support_user.id,
        actor_type="support",
        action="support_session_issued",
        resource_type="support_grant",
        resource_id=grant.id,
        metadata={"scopes": list(grant.scopes or []), "expires_at": expiry.isoformat()},
    )
    db.commit()
    return token, expiry
