"""Signed, expiring OAuth state tokens."""

import base64
import hashlib
import hmac
import json
import time
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.oauth_state import OAuthState


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def issue_oauth_state(business_id: int, secret: str, ttl_seconds: int = 600) -> str:
    payload = {
        "business_id": int(business_id),
        "exp": int(time.time()) + ttl_seconds,
        "nonce": secrets.token_urlsafe(18),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def verify_oauth_state(state: str, secret: str) -> dict:
    try:
        encoded, signature = state.split(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if int(payload["exp"]) < int(time.time()):
            raise ValueError
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        raise PermissionError("Invalid or expired OAuth state")


def register_oauth_state(db: Session, state: str, secret: str) -> dict:
    payload = verify_oauth_state(state, secret)
    db.add(OAuthState(
        nonce=payload["nonce"],
        business_id=payload["business_id"],
        expires_at=_utcnow() + timedelta(seconds=max(0, payload["exp"] - int(time.time()))),
    ))
    db.commit()
    return payload


def consume_oauth_state(db: Session, state: str, secret: str) -> dict:
    payload = verify_oauth_state(state, secret)
    result = db.execute(
        update(OAuthState)
        .where(
            OAuthState.nonce == payload["nonce"],
            OAuthState.business_id == payload["business_id"],
            OAuthState.consumed_at.is_(None),
            OAuthState.expires_at > _utcnow(),
        )
        .values(consumed_at=_utcnow())
    )
    if result.rowcount != 1:
        db.rollback()
        raise PermissionError("OAuth state has already been used or is unknown")
    db.commit()
    return payload
