"""User login, bearer session lifecycle, and audit log views."""

from datetime import datetime, timezone

import hashlib

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_authenticated_session, get_current_user, issue_token, require_admin_access, token_hash
from app.auth.passwords import verify_password
from app.core.config import settings
from app.db.dependencies import get_db
from app.models.audit_log import AuditLog
from app.models.auth_session import AuthSession
from app.models.business import Business, User
from app.models.saas import PlatformMembership
from app.middleware.security import LoginRateLimiter, RateLimitBackendUnavailable
from app.schemas.auth import AuditLogOut, AuthSessionOut, AuthUserOut, LoginOut, LoginRequest, MfaDisableRequest, MfaPrepareOut, MfaVerifyOut, MfaVerifyRequest
from app.services.audit_service import record_audit
from app.services.mfa_service import disable_mfa, enable_mfa, prepare_mfa, verify_mfa_code
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter(prefix="/auth")


_login_rate_limiter: LoginRateLimiter | None = None
_login_rate_limiter_config: tuple[object, ...] | None = None


def _get_login_rate_limiter() -> LoginRateLimiter:
    """Build the login limiter lazily so app import never requires Redis."""
    global _login_rate_limiter, _login_rate_limiter_config
    config = (
        settings.AUTH_LOGIN_RATE_LIMIT_ENABLED,
        settings.AUTH_LOGIN_RATE_LIMIT_REQUESTS,
        settings.AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        settings.AUTH_LOGIN_RATE_LIMIT_BACKEND,
        settings.REDIS_URL,
    )
    if _login_rate_limiter is None or _login_rate_limiter_config != config:
        _login_rate_limiter = LoginRateLimiter(
            enabled=settings.AUTH_LOGIN_RATE_LIMIT_ENABLED,
            max_attempts=settings.AUTH_LOGIN_RATE_LIMIT_REQUESTS,
            window_seconds=settings.AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS,
            backend=settings.AUTH_LOGIN_RATE_LIMIT_BACKEND,
            redis_url=settings.REDIS_URL,
            prefix="crm:auth-login:",
        )
        _login_rate_limiter_config = config
    return _login_rate_limiter


def _login_client_key(request: Request, email: str) -> str:
    client_ip = request.client.host if request.client else "unknown"
    if settings.RATE_LIMIT_TRUSTED_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            client_ip = forwarded
    return LoginRateLimiter.key(email, client_ip)


def _rate_limit_error(
    retry_after: int,
    *,
    limit: int | None = None,
    reset_at: int | None = None,
) -> HTTPException:
    headers = {"Retry-After": str(max(1, int(retry_after)))}
    if limit is not None:
        headers["X-RateLimit-Limit"] = str(max(1, int(limit)))
        headers["X-RateLimit-Remaining"] = "0"
    if reset_at is not None:
        headers["X-RateLimit-Reset"] = str(max(0, int(reset_at)))
    return HTTPException(
        status_code=429,
        detail={
            "code": "auth_rate_limited",
            "message": "Quá nhiều lần thử đăng nhập. Vui lòng thử lại sau.",
            "retry_after": max(1, int(retry_after)),
        },
        headers=headers,
    )


@router.post("/login", response_model=LoginOut)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    x_business_id: str | None = Header(default=None, alias="X-Business-Id"),
    x_device_label: str | None = Header(default=None, alias="X-Device-Label"),
):
    try:
        limiter = _get_login_rate_limiter()
    except (RateLimitBackendUnavailable, ValueError):
        raise HTTPException(
            status_code=503,
            detail="Bộ giới hạn đăng nhập tạm thời không khả dụng.",
            headers={"Retry-After": "5"},
        ) from None
    login_key = _login_client_key(request, payload.email)
    try:
        decision = limiter.check(login_key)
    except RateLimitBackendUnavailable:
        raise HTTPException(
            status_code=503,
            detail="Bộ giới hạn đăng nhập tạm thời không khả dụng.",
            headers={"Retry-After": "5"},
        ) from None
    if not decision.allowed:
        raise _rate_limit_error(
            decision.retry_after,
            limit=limiter.max_attempts,
            reset_at=decision.reset_at,
        )
    if x_business_id and not settings.ALLOW_LEGACY_TENANT_HEADER:
        raise HTTPException(status_code=400, detail="X-Business-Id không được dùng trong runtime này.")
    query = db.query(User).filter(User.email.ilike(payload.email.strip()), User.is_active.is_(True))
    if x_business_id:
        try:
            query = query.filter(User.business_id == int(x_business_id))
        except ValueError:
            raise HTTPException(status_code=422, detail="X-Business-Id không hợp lệ.") from None
    if payload.shop_slug:
        query = query.join(Business, Business.id == User.business_id).filter(Business.slug == payload.shop_slug.strip().lower())
    users = query.all()
    if len(users) != 1 or not verify_password(payload.password, users[0].password_hash):
        try:
            failure = limiter.record_failure(login_key)
        except RateLimitBackendUnavailable:
            raise HTTPException(
                status_code=503,
                detail="Bộ giới hạn đăng nhập tạm thời không khả dụng.",
                headers={"Retry-After": "5"},
            ) from None
        if not failure.allowed:
            raise _rate_limit_error(
                failure.retry_after,
                limit=limiter.max_attempts,
                reset_at=failure.reset_at,
            )
        raise HTTPException(status_code=401, detail="Email hoặc mật khẩu không đúng.")
    user = users[0]
    business = db.get(Business, user.business_id)
    is_platform_member = db.query(PlatformMembership.id).filter(
        PlatformMembership.user_id == user.id,
    ).first() is not None
    if business is not None and business.status != "active" and not is_platform_member:
        raise HTTPException(
            status_code=423,
            detail={"code": "business_suspended", "message": "Shop đang tạm khóa bởi quản trị nền tảng."},
        )
    token, expires_at = issue_token(
        user.id,
        business_id=user.business_id,
        role=user.role,
    )
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
    limiter.reset(login_key)
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
