"""User login, bearer session lifecycle, and audit log views."""

from datetime import datetime, timedelta, timezone

import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import AUTH_TTL_SECONDS, get_authenticated_session, get_current_user, issue_token, require_admin_access, token_hash
from app.auth.passwords import hash_password, validate_signup_password, verify_password
from app.core.config import settings
from app.db.dependencies import get_db
from app.models.audit_log import AuditLog
from app.models.auth_session import AuthSession
from app.models.business import Business, User
from app.models.saas import PlatformMembership
from app.models.signup import SignupEmailChallenge
from app.models.user_email_change import UserEmailChangeChallenge
from app.middleware.security import LoginRateLimiter, RateLimitBackendUnavailable
from app.schemas.auth import AuditLogOut, AuthSessionOut, AuthUserOut, EmailChangeRequest, EmailChangeRequestOut, EmailChangeVerify, EmailChangeVerifyOut, LoginOut, LoginRequest, MfaDisableRequest, MfaPrepareOut, MfaVerifyOut, MfaVerifyRequest, PasswordResetComplete, PasswordResetCompleteOut, PasswordResetRequest, PasswordResetRequestOut
from app.services.audit_service import record_audit
from app.services.customer_collection import contact_hash, generate_verification_code, hash_verification_code, mask_contact
from app.services.mfa_service import disable_mfa, enable_mfa, prepare_mfa, verify_mfa_code
from app.services.otp_delivery import OtpDeliveryError, OtpDeliveryNotConfigured, deliver_otp
from app.services.shop_otp_email import get_shop_otp_smtp_config
from app.tenancy.context import TenantContext
from app.tenancy.crm_session import get_tenant_db
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
    business = db.get(Business, user.business_id) if user.business_id is not None else None
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
        ttl_seconds=30 * 24 * 60 * 60 if payload.remember_me else AUTH_TTL_SECONDS,
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
    if user.business_id is not None:
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


@router.post("/password-reset/request", status_code=202, response_model=PasswordResetRequestOut)
def request_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    """Send a short-lived email code without disclosing whether an account exists."""
    email = payload.email
    query = db.query(User).filter(func.lower(User.email) == email, User.is_active.is_(True))
    if payload.shop_slug:
        query = query.join(Business, Business.id == User.business_id).filter(Business.slug == payload.shop_slug.strip().lower())
    users = query.with_for_update().limit(2).all()
    if len(users) != 1:
        return {"status": "accepted", "expires_in": 600, "retry_after": 60}

    user = users[0]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    scope = (
        SignupEmailChallenge.business_id.is_(None)
        if user.business_id is None
        else SignupEmailChallenge.business_id == user.business_id
    )
    latest = db.query(SignupEmailChallenge).filter(
        SignupEmailChallenge.email == email,
        SignupEmailChallenge.purpose == "password_reset",
        scope,
        SignupEmailChallenge.status.in_(("pending", "pending_delivery")),
    ).order_by(SignupEmailChallenge.created_at.desc(), SignupEmailChallenge.id.desc()).first()
    if latest is not None and latest.created_at is not None and (now - latest.created_at).total_seconds() < 60:
        return {"status": "accepted", "expires_in": 600, "retry_after": 60}

    recent_count = db.query(SignupEmailChallenge).filter(
        SignupEmailChallenge.email == email,
        SignupEmailChallenge.purpose == "password_reset",
        scope,
        SignupEmailChallenge.created_at >= now - timedelta(hours=1),
    ).count()
    if recent_count >= 5:
        return {"status": "accepted", "expires_in": 600, "retry_after": 60}

    code = generate_verification_code()
    challenge = SignupEmailChallenge(
        email=email,
        purpose="password_reset",
        business_id=user.business_id,
        role=user.role,
        code_hash=hash_verification_code(code),
        status="pending_delivery",
        expires_at=now + timedelta(minutes=10),
        created_at=now,
    )
    db.add(challenge)
    db.commit()

    try:
        delivery = deliver_otp(channel="email", destination=email, code=code)
        if not delivery.delivered or delivery.provider != "smtp":
            raise OtpDeliveryNotConfigured("Password reset requires email OTP delivery.")
    except (OtpDeliveryNotConfigured, OtpDeliveryError, ValueError, OSError):
        challenge.status = "delivery_failed"
        db.commit()
        return {"status": "accepted", "expires_in": 600, "retry_after": 60}

    challenge.status = "pending"
    for pending in db.query(SignupEmailChallenge).filter(
        SignupEmailChallenge.email == email,
        SignupEmailChallenge.purpose == "password_reset",
        scope,
        SignupEmailChallenge.id != challenge.id,
        SignupEmailChallenge.status.in_(("pending", "pending_delivery")),
    ).all():
        pending.status = "superseded"
    db.commit()
    return {"status": "accepted", "expires_in": 600, "retry_after": 60}


@router.post("/password-reset/complete", response_model=PasswordResetCompleteOut)
def complete_password_reset(payload: PasswordResetComplete, db: Session = Depends(get_db)):
    try:
        validate_signup_password(payload.new_password)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    query = db.query(SignupEmailChallenge).filter(
        SignupEmailChallenge.email == payload.email,
        SignupEmailChallenge.purpose == "password_reset",
        SignupEmailChallenge.status == "pending",
    )
    if payload.shop_slug:
        query = query.join(Business, Business.id == SignupEmailChallenge.business_id).filter(Business.slug == payload.shop_slug.strip().lower())
    challenge = query.order_by(SignupEmailChallenge.created_at.desc(), SignupEmailChallenge.id.desc()).with_for_update().first()
    invalid_code = HTTPException(status_code=422, detail="Mã không hợp lệ hoặc đã hết hạn. Hãy yêu cầu mã mới.")
    if challenge is None:
        raise invalid_code

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if challenge.expires_at <= now or challenge.attempts >= challenge.max_attempts:
        challenge.status = "expired" if challenge.expires_at <= now else "locked"
        db.commit()
        raise invalid_code
    challenge.attempts += 1
    if not hmac.compare_digest(hash_verification_code(payload.otp), challenge.code_hash):
        if challenge.attempts >= challenge.max_attempts:
            challenge.status = "locked"
        db.commit()
        raise invalid_code

    user_query = db.query(User).filter(func.lower(User.email) == payload.email, User.is_active.is_(True))
    if challenge.business_id is None:
        user_query = user_query.filter(User.business_id.is_(None))
    else:
        user_query = user_query.filter(User.business_id == challenge.business_id)
    if payload.shop_slug:
        user_query = user_query.join(Business, Business.id == User.business_id).filter(Business.slug == payload.shop_slug.strip().lower())
    users = user_query.with_for_update().limit(2).all()
    if len(users) != 1:
        challenge.status = "invalid"
        db.commit()
        raise invalid_code

    user = users[0]
    user.password_hash = hash_password(payload.new_password)
    challenge.status = "verified"
    challenge.verified_at = now
    session_count = db.query(AuthSession).filter(
        AuthSession.user_id == user.id,
        AuthSession.revoked_at.is_(None),
    ).update({AuthSession.revoked_at: now}, synchronize_session=False)
    user_scope = (
        SignupEmailChallenge.business_id.is_(None)
        if user.business_id is None
        else SignupEmailChallenge.business_id == user.business_id
    )
    for pending in db.query(SignupEmailChallenge).filter(
        SignupEmailChallenge.email == payload.email,
        SignupEmailChallenge.purpose == "password_reset",
        user_scope,
        SignupEmailChallenge.id != challenge.id,
        SignupEmailChallenge.status.in_(("pending", "pending_delivery")),
    ).all():
        pending.status = "superseded"
    if user.business_id is not None:
        record_audit(
            db,
            business_id=user.business_id,
            user_id=user.id,
            action="password_reset",
            resource_type="user_credential",
            resource_id=user.id,
            metadata={"active_sessions_revoked": int(session_count)},
        )
    db.commit()
    return {"status": "password_reset"}


@router.post("/email-change/request", status_code=202, response_model=EmailChangeRequestOut)
def request_email_change(
    payload: EmailChangeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    smtp_settings_db: Session = Depends(get_tenant_db),
):
    """Send a one-time verification code; keep the current login email active until verified."""
    if user.business_id is None:
        raise HTTPException(status_code=403, detail="Chỉ tài khoản thuộc shop mới có thể đổi email tại đây.")
    locked_user = db.query(User).filter(
        User.id == user.id,
        User.business_id == user.business_id,
        User.is_active.is_(True),
    ).with_for_update().first()
    if locked_user is None:
        raise HTTPException(status_code=401, detail="Mật khẩu hiện tại không đúng.")

    new_email = payload.new_email
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    latest = db.query(UserEmailChangeChallenge).filter(
        UserEmailChangeChallenge.user_id == locked_user.id,
    ).order_by(UserEmailChangeChallenge.created_at.desc(), UserEmailChangeChallenge.id.desc()).first()
    if latest is not None and latest.created_at is not None:
        cooldown = int((latest.created_at + timedelta(seconds=60) - now).total_seconds())
        if cooldown > 0:
            raise HTTPException(
                status_code=429,
                detail="Vui lòng đợi trước khi yêu cầu mã xác minh khác.",
                headers={"Retry-After": str(cooldown)},
            )

    cutoff = now - timedelta(hours=1)
    recent_query = db.query(UserEmailChangeChallenge).filter(
        UserEmailChangeChallenge.user_id == locked_user.id,
        UserEmailChangeChallenge.created_at >= cutoff,
    )
    recent_count = recent_query.count()
    if recent_count >= 5:
        oldest = recent_query.order_by(UserEmailChangeChallenge.created_at.asc()).first()
        retry_after = max(1, int(((oldest.created_at + timedelta(hours=1)) - now).total_seconds())) if oldest else 3600
        raise HTTPException(
            status_code=429,
            detail="Đã đạt giới hạn yêu cầu mã xác minh email trong giờ này.",
            headers={"Retry-After": str(retry_after)},
        )

    code = generate_verification_code()
    challenge = UserEmailChangeChallenge(
        user_id=locked_user.id,
        business_id=locked_user.business_id,
        new_email=new_email,
        code_hash=hash_verification_code(code),
        status="request_started",
        expires_at=now + timedelta(minutes=10),
        created_at=now,
    )
    db.add(challenge)
    email_hash = contact_hash("email", new_email)[:16]

    if not locked_user.password_hash or not verify_password(payload.current_password, locked_user.password_hash):
        challenge.status = "password_rejected"
        record_audit(
            db,
            business_id=locked_user.business_id,
            user_id=locked_user.id,
            action="user_email_change_rejected",
            resource_type="user_email",
            resource_id=locked_user.id,
            metadata={"new_email_hash": email_hash, "reason": "invalid_password"},
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Mật khẩu hiện tại không đúng.")

    if new_email == str(locked_user.email or "").strip().lower():
        challenge.status = "same_email"
        record_audit(
            db,
            business_id=locked_user.business_id,
            user_id=locked_user.id,
            action="user_email_change_rejected",
            resource_type="user_email",
            resource_id=locked_user.id,
            metadata={"new_email_hash": email_hash, "reason": "same_email"},
        )
        db.commit()
        raise HTTPException(status_code=409, detail="Email mới giống email hiện tại.")
    if db.query(User.id).filter(
        User.business_id == locked_user.business_id,
        func.lower(User.email) == new_email,
        User.id != locked_user.id,
    ).first():
        challenge.status = "email_in_use"
        record_audit(
            db,
            business_id=locked_user.business_id,
            user_id=locked_user.id,
            action="user_email_change_rejected",
            resource_type="user_email",
            resource_id=locked_user.id,
            metadata={"new_email_hash": email_hash, "reason": "email_in_use"},
        )
        db.commit()
        raise HTTPException(status_code=409, detail="Email này đã được dùng trong shop.")

    for pending in db.query(UserEmailChangeChallenge).filter(
        UserEmailChangeChallenge.user_id == locked_user.id,
        UserEmailChangeChallenge.status.in_(("pending", "pending_delivery")),
    ).all():
        pending.status = "superseded"
    challenge.status = "pending_delivery"
    record_audit(
        db,
        business_id=locked_user.business_id,
        user_id=locked_user.id,
        action="user_email_change_requested",
        resource_type="user_email",
        resource_id=locked_user.id,
        metadata={"new_email_hash": email_hash},
    )
    db.commit()

    try:
        delivery = deliver_otp(
            channel="email",
            destination=new_email,
            code=code,
            smtp_config=get_shop_otp_smtp_config(smtp_settings_db, locked_user.business_id),
        )
        # Email-change challenges must prove mailbox access. A development
        # in-chat fallback is not proof that the new address belongs to them.
        if not delivery.delivered or delivery.provider != "smtp":
            raise OtpDeliveryNotConfigured("Email OTP chưa được gửi qua SMTP.")
    except (OtpDeliveryNotConfigured, OtpDeliveryError, ValueError, OSError) as exc:
        challenge.status = "delivery_failed"
        record_audit(
            db,
            business_id=locked_user.business_id,
            user_id=locked_user.id,
            action="user_email_change_delivery_failed",
            resource_type="user_email",
            resource_id=locked_user.id,
            metadata={"new_email_hash": email_hash, "error_type": type(exc).__name__},
        )
        db.commit()
        raise HTTPException(status_code=503, detail="Chưa gửi được mã xác minh email. Email đăng nhập chưa thay đổi.") from exc

    challenge.status = "pending"
    db.commit()
    return {
        "status": "verification_sent",
        "email": mask_contact("email", new_email),
        "expires_in": 600,
        "retry_after": 60,
    }


@router.post("/email-change/verify", response_model=EmailChangeVerifyOut)
def verify_email_change(
    payload: EmailChangeVerify,
    user: User = Depends(get_current_user),
    auth_session: AuthSession = Depends(get_authenticated_session),
    db: Session = Depends(get_db),
):
    if user.business_id is None:
        raise HTTPException(status_code=403, detail="Chỉ tài khoản thuộc shop mới có thể đổi email tại đây.")
    locked_user = db.query(User).filter(
        User.id == user.id,
        User.business_id == user.business_id,
        User.is_active.is_(True),
    ).with_for_update().first()
    challenge = db.query(UserEmailChangeChallenge).filter(
        UserEmailChangeChallenge.user_id == user.id,
        UserEmailChangeChallenge.business_id == user.business_id,
        UserEmailChangeChallenge.status == "pending",
    ).order_by(UserEmailChangeChallenge.created_at.desc(), UserEmailChangeChallenge.id.desc()).with_for_update().first()
    if locked_user is None or challenge is None:
        raise HTTPException(status_code=422, detail="Không có mã xác minh đang chờ. Hãy yêu cầu mã mới.")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if challenge.expires_at <= now:
        challenge.status = "expired"
        db.commit()
        raise HTTPException(status_code=422, detail="Mã xác minh đã hết hạn. Hãy yêu cầu mã mới.")
    if challenge.attempts >= challenge.max_attempts:
        challenge.status = "locked"
        db.commit()
        raise HTTPException(status_code=422, detail="Mã xác minh đã bị khóa. Hãy yêu cầu mã mới.")
    challenge.attempts += 1
    if not hmac.compare_digest(hash_verification_code(payload.otp), challenge.code_hash):
        if challenge.attempts >= challenge.max_attempts:
            challenge.status = "locked"
        db.commit()
        raise HTTPException(status_code=422, detail="Mã xác minh không đúng.")

    if db.query(User.id).filter(
        User.business_id == locked_user.business_id,
        func.lower(User.email) == challenge.new_email,
        User.id != locked_user.id,
    ).first():
        challenge.status = "conflict"
        db.commit()
        raise HTTPException(status_code=409, detail="Email này đã được dùng trong shop.")

    old_email_hash = contact_hash("email", str(locked_user.email))[:16]
    new_email_hash = contact_hash("email", challenge.new_email)[:16]
    locked_user.email = challenge.new_email
    challenge.status = "verified"
    challenge.verified_at = now
    db.query(AuthSession).filter(
        AuthSession.user_id == locked_user.id,
        AuthSession.id != auth_session.id,
        AuthSession.revoked_at.is_(None),
    ).update({AuthSession.revoked_at: now}, synchronize_session=False)
    record_audit(
        db,
        business_id=locked_user.business_id,
        user_id=locked_user.id,
        action="user_email_changed",
        resource_type="user_email",
        resource_id=locked_user.id,
        metadata={"old_email_hash": old_email_hash, "new_email_hash": new_email_hash, "other_sessions_revoked": True},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email này đã được dùng trong shop.") from exc
    return {"status": "verified", "email": locked_user.email}


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
    if user.business_id is not None:
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
    if user.business_id is not None:
        record_audit(db, business_id=user.business_id, user_id=user.id, action="session_revoked", resource_type="auth_session", resource_id=session.id)
    db.commit()


@router.post("/mfa/prepare", response_model=MfaPrepareOut)
def prepare_mfa_enrollment(
    user: User = Depends(require_admin_access),
    db: Session = Depends(get_db),
):
    provisioning_uri = prepare_mfa(user)
    if user.business_id is not None:
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
    if user.business_id is not None:
        record_audit(db, business_id=user.business_id, user_id=user.id, action="mfa_disabled", resource_type="user", resource_id=user.id, metadata={"status": "disabled"})
    db.commit()


@router.post("/mfa/verify", response_model=MfaVerifyOut)
def verify_mfa_enrollment(
    payload: MfaVerifyRequest,
    session: AuthSession = Depends(get_authenticated_session),
    db: Session = Depends(get_db),
):
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Mã MFA không đúng hoặc đã hết hạn.")
    if not verify_mfa_code(user, payload.code):
        raise HTTPException(status_code=422, detail="Mã MFA không đúng hoặc đã hết hạn.")
    enable_mfa(user)
    session.mfa_verified = True
    if user.business_id is not None:
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
