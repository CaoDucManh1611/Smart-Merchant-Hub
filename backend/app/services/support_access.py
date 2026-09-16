"""Owner-approved, short-lived support access for tenant operations.

Support sessions are deliberately separate from ordinary shop sessions.  The
signed token carries only routing metadata; every request re-checks the grant
in the platform database so revocation is immediate.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.platform_control import PlatformAudit, PlatformBusiness, PlatformUser, SupportGrant


MAX_GRANT_MINUTES = 60
ALLOWED_SCOPES = frozenset({"settings:read", "channels:diagnose", "jobs:retry"})
DENIED_CONTENT_SCOPES = frozenset({"conversation:read", "customer:read", "order:read", "*"})


@dataclass(frozen=True)
class SupportSession:
    grant_id: int
    business_id: int
    support_user_id: int
    scopes: tuple[str, ...]
    expires_at: datetime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def normalize_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
    """Validate and canonicalize the narrow operational scope allow-list."""

    values = tuple(
        sorted(
            {
                str(scope).strip().lower().replace(".", ":")
                for scope in scopes
                if str(scope).strip()
            }
        )
    )
    if not values:
        raise ValueError("Support grant cần ít nhất một phạm vi thao tác.")
    denied = DENIED_CONTENT_SCOPES.intersection(values)
    unsupported = set(values).difference(ALLOWED_SCOPES)
    if denied or unsupported:
        raise ValueError("Support grant chỉ được dùng các phạm vi vận hành được cho phép.")
    return values


def _record_audit(
    db: Session,
    *,
    action: str,
    business_id: int | None,
    actor_user_id: int | None,
    grant_id: int | None = None,
    allowed: bool | None = None,
) -> None:
    metadata: dict[str, object] = {}
    if grant_id is not None:
        metadata["grant_id"] = int(grant_id)
    if allowed is not None:
        metadata["allowed"] = bool(allowed)
    db.add(
        PlatformAudit(
            actor_user_id=actor_user_id,
            business_id=business_id,
            action=action,
            resource_type="support_grant",
            resource_id=str(grant_id) if grant_id is not None else None,
            metadata_json=metadata,
        )
    )


def create_support_grant(
    db: Session,
    *,
    business_id: int,
    granted_by_user_id: int,
    support_user_id: int,
    reason: str,
    scopes: Iterable[str],
    expires_at: datetime,
) -> SupportGrant:
    """Create an owner-approved grant and audit the decision."""

    reason = str(reason or "").strip()
    if len(reason) < 5:
        raise ValueError("Cần nêu lý do cấp quyền hỗ trợ.")
    if len(reason) > 2000:
        raise ValueError("Lý do hỗ trợ quá dài.")
    if int(business_id) <= 0 or int(granted_by_user_id) <= 0 or int(support_user_id) <= 0:
        raise ValueError("Thông tin shop hoặc người dùng không hợp lệ.")
    scope_values = normalize_scopes(scopes)
    expiry = _naive_utc(expires_at)
    now = _utcnow()
    if expiry <= now:
        raise ValueError("Thời hạn hỗ trợ phải nằm trong tương lai.")
    if expiry > now + timedelta(minutes=MAX_GRANT_MINUTES):
        raise ValueError("Quyền hỗ trợ tối đa 60 phút.")

    business = db.scalar(select(PlatformBusiness).where(PlatformBusiness.id == int(business_id)))
    if business is None:
        raise LookupError("Shop không tồn tại trên control plane.")
    owner = db.scalar(
        select(PlatformUser).where(
            PlatformUser.id == int(granted_by_user_id),
            PlatformUser.business_id == int(business_id),
            PlatformUser.role == "owner",
            PlatformUser.is_active.is_(True),
        )
    )
    if owner is None:
        _record_audit(
            db,
            action="support_grant_denied",
            business_id=int(business_id),
            actor_user_id=int(granted_by_user_id),
            allowed=False,
        )
        db.flush()
        raise PermissionError("Chỉ chủ shop mới được cấp quyền hỗ trợ.")
    support_user = db.scalar(
        select(PlatformUser).where(
            PlatformUser.id == int(support_user_id),
            PlatformUser.is_active.is_(True),
        )
    )
    if support_user is None:
        raise LookupError("Tài khoản hỗ trợ không tồn tại hoặc đã bị khóa.")
    if support_user.business_id is not None or str(support_user.role or "").lower() not in {
        "support",
        "platform_support",
        "platform_admin",
    }:
        _record_audit(
            db,
            action="support_grant_denied",
            business_id=int(business_id),
            actor_user_id=int(granted_by_user_id),
            allowed=False,
        )
        db.flush()
        raise PermissionError("Chỉ tài khoản hỗ trợ nền tảng mới được nhận grant.")

    grant = SupportGrant(
        business_id=int(business_id),
        granted_by_user_id=int(granted_by_user_id),
        support_user_id=int(support_user_id),
        reason=reason,
        scopes=list(scope_values),
        expires_at=expiry,
    )
    db.add(grant)
    db.flush()
    _record_audit(
        db,
        action="support_grant_created",
        business_id=int(business_id),
        actor_user_id=int(granted_by_user_id),
        grant_id=grant.id,
        allowed=True,
    )
    return grant


def revoke_support_grant(db: Session, *, grant_id: int, actor_user_id: int) -> SupportGrant:
    grant = db.get(SupportGrant, int(grant_id))
    if grant is None:
        raise LookupError("Quyền hỗ trợ không tồn tại.")
    owner = db.scalar(
        select(PlatformUser).where(
            PlatformUser.id == int(actor_user_id),
            PlatformUser.business_id == grant.business_id,
            PlatformUser.role == "owner",
            PlatformUser.is_active.is_(True),
        )
    )
    if owner is None:
        _record_audit(
            db,
            action="support_grant_revoke_denied",
            business_id=grant.business_id,
            actor_user_id=int(actor_user_id),
            grant_id=grant.id,
            allowed=False,
        )
        db.flush()
        raise PermissionError("Chỉ chủ shop mới được thu hồi quyền hỗ trợ.")
    if grant.revoked_at is None:
        grant.revoked_at = _utcnow()
    _record_audit(
        db,
        action="support_grant_revoked",
        business_id=grant.business_id,
        actor_user_id=int(actor_user_id),
        grant_id=grant.id,
        allowed=True,
    )
    db.flush()
    return grant


def _signing_key() -> bytes:
    value = str(settings.AUTH_SECRET or "").strip()
    if not value and settings.ENVIRONMENT.strip().lower() == "production":
        raise RuntimeError("AUTH_SECRET must be configured in production")
    value = value or str(settings.CHANNEL_ENCRYPTION_KEY or settings.APP_NAME)
    return value.encode("utf-8")


def issue_support_token(db: Session, *, grant_id: int, support_user_id: int) -> tuple[str, datetime]:
    grant = db.get(SupportGrant, int(grant_id))
    if grant is None:
        raise LookupError("Quyền hỗ trợ không tồn tại.")
    if grant.support_user_id != int(support_user_id):
        raise PermissionError("Quyền hỗ trợ không thuộc tài khoản này.")
    support_user = db.scalar(
        select(PlatformUser).where(
            PlatformUser.id == int(support_user_id),
            PlatformUser.is_active.is_(True),
        )
    )
    if support_user is None or support_user.business_id is not None:
        raise PermissionError("Tài khoản hỗ trợ không còn hoạt động.")
    if grant.revoked_at is not None or _naive_utc(grant.expires_at) <= _utcnow():
        raise PermissionError("Quyền hỗ trợ đã hết hạn hoặc bị thu hồi.")
    scopes = normalize_scopes(grant.scopes if isinstance(grant.scopes, list) else [])
    expires_at = _naive_utc(grant.expires_at)
    payload = {
        "typ": "support",
        "grant_id": int(grant.id),
        "business_id": int(grant.business_id),
        "support_user_id": int(support_user_id),
        "scopes": list(scopes),
        # ``expires_at`` is a UTC-naive value in our SQL models.  Attach UTC
        # explicitly; calling ``timestamp()`` on a naive datetime would use
        # the host's local timezone and shorten the token by several hours.
        "exp": int(expires_at.replace(tzinfo=timezone.utc).timestamp()),
        "jti": secrets.token_urlsafe(12),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(_signing_key(), encoded.encode(), hashlib.sha256).digest()
    token = "support." + encoded + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return token, expires_at


def _decode_support_token(token: str) -> dict:
    try:
        prefix, encoded, signature = str(token or "").split(".", 2)
        if prefix != "support":
            raise ValueError
        expected = hmac.new(_signing_key(), encoded.encode(), hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(signature + "===")
        if not hmac.compare_digest(expected, supplied):
            raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(encoded + "===").decode())
        expiry = datetime.fromtimestamp(int(payload["exp"]), timezone.utc).replace(tzinfo=None)
        if payload.get("typ") != "support" or expiry <= _utcnow():
            raise ValueError
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise PermissionError("Phiên hỗ trợ không hợp lệ hoặc đã hết hạn.") from None


def validate_support_access(
    db: Session,
    *,
    token: str,
    business_id: int,
    scope: str,
) -> SupportSession:
    """Validate signature, route, current grant and requested scope."""

    payload = _decode_support_token(token)
    requested = str(scope or "").strip().lower()
    try:
        grant_id = int(payload["grant_id"])
        token_business = int(payload["business_id"])
        support_user_id = int(payload["support_user_id"])
    except (KeyError, TypeError, ValueError):
        raise PermissionError("Phiên hỗ trợ không hợp lệ.") from None
    if token_business != int(business_id):
        raise PermissionError("Phiên hỗ trợ không thuộc shop này.")
    grant = db.get(SupportGrant, grant_id)
    now = _utcnow()
    support_user = db.scalar(
        select(PlatformUser).where(
            PlatformUser.id == support_user_id,
            PlatformUser.is_active.is_(True),
        )
    )
    if (
        grant is None
        or grant.business_id != int(business_id)
        or grant.support_user_id != support_user_id
        or grant.revoked_at is not None
        or _naive_utc(grant.expires_at) <= now
        or support_user is None
        or support_user.business_id is not None
    ):
        _record_audit(
            db,
            action="support_access_denied",
            business_id=int(business_id),
            actor_user_id=support_user_id,
            grant_id=grant_id,
            allowed=False,
        )
        db.flush()
        raise PermissionError("Quyền hỗ trợ đã hết hạn, bị thu hồi hoặc không hợp lệ.")
    granted_scopes = normalize_scopes(grant.scopes if isinstance(grant.scopes, list) else [])
    if requested not in granted_scopes:
        _record_audit(
            db,
            action="support_access_denied",
            business_id=int(business_id),
            actor_user_id=support_user_id,
            grant_id=grant_id,
            allowed=False,
        )
        db.flush()
        raise PermissionError("Phiên hỗ trợ không có phạm vi thao tác này.")
    _record_audit(
        db,
        action="support_access_allowed",
        business_id=int(business_id),
        actor_user_id=support_user_id,
        grant_id=grant_id,
        allowed=True,
    )
    db.flush()
    return SupportSession(
        grant_id=grant_id,
        business_id=int(business_id),
        support_user_id=support_user_id,
        scopes=granted_scopes,
        expires_at=_naive_utc(grant.expires_at),
    )


def validate_support_token(db: Session, *, token: str, scope: str) -> SupportSession:
    """Resolve the signed shop id and re-check the current platform grant."""

    payload = _decode_support_token(token)
    try:
        business_id = int(payload["business_id"])
    except (KeyError, TypeError, ValueError):
        raise PermissionError("Phiên hỗ trợ không hợp lệ.") from None
    return validate_support_access(
        db,
        token=token,
        business_id=business_id,
        scope=scope,
    )


__all__ = [
    "ALLOWED_SCOPES",
    "MAX_GRANT_MINUTES",
    "SupportSession",
    "create_support_grant",
    "issue_support_token",
    "normalize_scopes",
    "revoke_support_grant",
    "validate_support_access",
    "validate_support_token",
]
