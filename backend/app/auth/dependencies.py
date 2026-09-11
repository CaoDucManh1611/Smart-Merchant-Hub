"""Bearer session validation and role permissions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.dependencies import get_db
from app.models.auth_session import AuthSession
from app.models.business import Business, User
from app.services.permission_service import permission_allowed


AUTH_TTL_SECONDS = 8 * 60 * 60


def _secret() -> bytes:
    value = settings.AUTH_SECRET.strip()
    if not value and settings.ENVIRONMENT.strip().lower() == "production":
        raise RuntimeError("AUTH_SECRET must be configured in production")
    # Keep the local demo compatible, but never use this fallback in a
    # deployed environment.  Production validation rejects empty secrets.
    value = value or settings.CHANNEL_ENCRYPTION_KEY or settings.APP_NAME
    return value.encode("utf-8")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(user_id: int, *, ttl_seconds: int = AUTH_TTL_SECONDS) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None).timestamp() + ttl_seconds
    payload = {"sub": int(user_id), "exp": int(expires_at), "jti": secrets.token_urlsafe(16)}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(_secret(), encoded.encode(), hashlib.sha256).digest()
    token = f"{encoded}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
    return token, datetime.fromtimestamp(expires_at, timezone.utc).replace(tzinfo=None)


def _decode_token(token: str) -> dict:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(_secret(), encoded.encode(), hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(signature + "===")
        if not hmac.compare_digest(expected, supplied):
            raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(encoded + "===").decode())
        if int(payload["exp"]) <= int(time.time()):
            raise ValueError
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Bearer token không hợp lệ hoặc đã hết hạn.") from None


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Yêu cầu đăng nhập.")
    token = authorization[7:].strip()
    payload = _decode_token(token)
    session = db.query(AuthSession).filter(
        AuthSession.token_hash == token_hash(token),
        AuthSession.revoked_at.is_(None),
    ).first()
    if session is None or session.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(status_code=401, detail="Phiên đăng nhập không còn hiệu lực.")
    if int(payload.get("sub", 0)) != session.user_id:
        raise HTTPException(status_code=401, detail="Bearer token không hợp lệ.")
    user = db.query(User).filter(User.id == session.user_id, User.is_active.is_(True)).first()
    if user is None or user.business_id is None:
        raise HTTPException(status_code=401, detail="Tài khoản không còn hoạt động.")
    request.state.business_id = user.business_id
    request.state.user_id = user.id
    request.state.user_role = user.role
    return user


def get_optional_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    if not authorization:
        return None
    return get_current_user(request=request, authorization=authorization, db=db)


def require_permission(permission: str):
    """Return a dependency enforcing the minimal role for a permission."""
    resource, action = (permission.split(":", 1) + ["read"])[:2] if ":" in permission else (permission, "read")
    def dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if permission_allowed(db, user, resource=resource, action=action):
            return user
        raise HTTPException(status_code=403, detail="Bạn không có quyền thực hiện thao tác này.")
    return dependency


def _active_business_id(request: Request, user: User | None, x_business_id: str | None) -> int | None:
    if user is not None:
        return user.business_id
    state_id = getattr(request.state, "business_id", None) or getattr(request.state, "channel_business_id", None)
    if state_id is not None:
        return int(state_id)
    if x_business_id:
        try:
            return int(x_business_id)
        except ValueError:
            return None
    return None


def _ensure_business_active(db: Session, business_id: int | None) -> None:
    if business_id is None:
        return
    business = db.get(Business, business_id)
    if business is not None and business.status != "active":
        raise HTTPException(
            status_code=423,
            detail={"code": "business_suspended", "message": "Shop đang tạm khóa bởi quản trị nền tảng."},
        )


def require_write_access(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
    x_business_id: str | None = Header(default=None, alias="X-Business-Id"),
) -> User | None:
    """Enforce write permissions whenever a caller presents a bearer token.

    Development deployments historically accepted the tenant header without
    authentication, so the dependency keeps that compatibility path.  Once a
    session token is supplied, however, a viewer (or an unknown legacy role)
    can never mutate CRM data.
    """
    if user is None:
        if settings.ENVIRONMENT.strip().lower() == "production":
            raise HTTPException(status_code=401, detail="Yêu cầu đăng nhập.")
        _ensure_business_active(db, _active_business_id(request, user, x_business_id))
        return None
    _ensure_business_active(db, _active_business_id(request, user, x_business_id))
    if (user.role or "").lower() not in {"owner", "admin", "agent"}:
        raise HTTPException(status_code=403, detail="Bạn không có quyền thực hiện thao tác này.")
    return user


def require_admin_access(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
    x_business_id: str | None = Header(default=None, alias="X-Business-Id"),
) -> User | None:
    """Require owner/admin for team, security, and configuration writes."""
    if user is None:
        if settings.ENVIRONMENT.strip().lower() == "production":
            raise HTTPException(status_code=401, detail="Yêu cầu đăng nhập.")
        _ensure_business_active(db, _active_business_id(request, user, x_business_id))
        return None
    _ensure_business_active(db, _active_business_id(request, user, x_business_id))
    if (user.role or "").lower() not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Chỉ quản trị viên mới được thực hiện thao tác này.")
    return user
