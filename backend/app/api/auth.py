"""User login, bearer session lifecycle, and audit log views."""

from datetime import datetime, timezone

import hashlib

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_authenticated_session, get_current_user, issue_token, require_admin_access, token_hash
from app.auth.passwords import verify_password
from app.db.dependencies import get_db
from app.models.audit_log import AuditLog
from app.models.auth_session import AuthSession
from app.models.business import User
from app.schemas.auth import AuditLogOut, AuthSessionOut, AuthUserOut, LoginOut, LoginRequest, MfaDisableRequest, MfaPrepareOut, MfaVerifyOut, MfaVerifyRequest
from app.services.audit_service import record_audit
from app.services.mfa_service import disable_mfa, enable_mfa, prepare_mfa, verify_mfa_code
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter(prefix="/auth")


@router.post("/login", response_model=LoginOut)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    x_business_id: str | None = Header(default=None, alias="X-Business-Id"),
    x_device_label: str | None = Header(default=None, alias="X-Device-Label"),
):
    query = db.query(User).filter(User.email.ilike(payload.email.strip()), User.is_active.is_(True))
    if x_business_id:
        try:
            query = query.filter(User.business_id == int(x_business_id))
        except ValueError:
            raise HTTPException(status_code=422, detail="X-Business-Id không hợp lệ.") from None
    users = query.all()
    if len(users) != 1 or not verify_password(payload.password, users[0].password_hash):
        raise HTTPException(status_code=401, detail="Email hoặc mật khẩu không đúng.")
    user = users[0]
    token, expires_at = issue_token(user.id)
    db.add(AuthSession(
        user_id=user.id,
        token_hash=token_hash(token),
        expires_at=expires_at,
        device_label=(x_device_label or "").strip()[:120] or None,
        user_agent_hash=hashlib.sha256(request.headers.get("user-agent", "").encode()).hexdigest(),
        ip_hash=hashlib.sha256((request.client.host if request.client else "unknown").encode()).hexdigest(),
        mfa_verified=user.mfa_status != "enabled",
    ))
    record_audit(
        db,
        business_id=user.business_id,
        user_id=user.id,
        action="login",
        resource_type="auth_session",
        metadata={"email": user.email},
    )
    db.commit()
    return LoginOut(
        access_token=token,
        expires_at=expires_at,
        user=AuthUserOut.model_validate(user),
        mfa_required=user.mfa_status == "enabled",
    )


@router.get("/me", response_model=AuthUserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/logout", status_code=204)
def logout(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    token = authorization[7:].strip()
    session = db.query(AuthSession).filter(AuthSession.token_hash == token_hash(token)).first()
    if session is not None:
        session.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record_audit(db, business_id=user.business_id, user_id=user.id, action="logout", resource_type="auth_session")
    db.commit()


@router.get("/sessions", response_model=list[AuthSessionOut])
def list_sessions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(AuthSession).filter(
        AuthSession.user_id == user.id,
    ).order_by(AuthSession.created_at.desc(), AuthSession.id.desc()).all()


@router.post("/sessions/{session_id}/revoke", status_code=204)
def revoke_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = db.query(AuthSession).filter(
        AuthSession.id == session_id,
        AuthSession.user_id == user.id,
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Phiên đăng nhập không tồn tại.")
    if session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record_audit(db, business_id=user.business_id, user_id=user.id, action="session_revoked", resource_type="auth_session", resource_id=session.id)
    db.commit()


@router.post("/mfa/prepare", response_model=MfaPrepareOut)
def prepare_mfa_enrollment(
    user: User = Depends(require_admin_access),
    db: Session = Depends(get_db),
):
    provisioning_uri = prepare_mfa(user)
    record_audit(db, business_id=user.business_id, user_id=user.id, action="mfa_prepared", resource_type="user", resource_id=user.id, metadata={"status": "prepared"})
    db.commit()
    return MfaPrepareOut(status="prepared", provisioning_uri=provisioning_uri)


@router.post("/mfa/disable", status_code=204)
def disable_mfa_enrollment(
    payload: MfaDisableRequest,
    user: User = Depends(require_admin_access),
    db: Session = Depends(get_db),
):
    if not payload.confirm:
        raise HTTPException(status_code=422, detail="Cần xác nhận trước khi tắt MFA.")
    disable_mfa(user)
    record_audit(db, business_id=user.business_id, user_id=user.id, action="mfa_disabled", resource_type="user", resource_id=user.id, metadata={"status": "disabled"})
    db.commit()


@router.post("/mfa/verify", response_model=MfaVerifyOut)
def verify_mfa_enrollment(
    payload: MfaVerifyRequest,
    session: AuthSession = Depends(get_authenticated_session),
    db: Session = Depends(get_db),
):
    user = db.get(User, session.user_id)
    if user is None or not verify_mfa_code(user, payload.code):
        raise HTTPException(status_code=401, detail="Mã MFA không đúng hoặc đã hết hạn.")
    enable_mfa(user)
    session.mfa_verified = True
    record_audit(db, business_id=user.business_id, user_id=user.id, actor_type="staff", action="mfa_verified", resource_type="auth_session", resource_id=session.id, metadata={"status": "enabled"})
    db.commit()
    return MfaVerifyOut(status="enabled", mfa_verified=True)


@router.get("/audit-logs", response_model=list[AuditLogOut])
def list_audit_logs(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    user: User = Depends(get_current_user),
    limit: int = Query(default=100, ge=1, le=500),
):
    if user.business_id != tenant.business_id or user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Chỉ quản trị viên mới xem được audit log.")
    rows = db.query(AuditLog).filter(
        AuditLog.business_id == tenant.business_id,
    ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).all()
    return rows
