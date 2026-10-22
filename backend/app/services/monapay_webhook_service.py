"""Authenticate and idempotently record MONA Pay incoming-payment webhooks."""

from datetime import datetime, timezone
import hashlib
import hmac
import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.monapay_transaction import MonaIncomingTransaction


def verify_signature(raw_body: bytes, timestamp: str, signature: str, secret: str, *, now: int | None = None) -> None:
    if not secret:
        raise HTTPException(503, "MONA Pay webhook is not configured")
    if not timestamp.isascii() or not timestamp.isdigit():
        raise HTTPException(400, "Invalid MONA Pay timestamp")
    if abs((now if now is not None else int(datetime.now(timezone.utc).timestamp())) - int(timestamp)) > 300:
        raise HTTPException(400, "MONA Pay webhook timestamp expired")
    if len(signature) != 71 or not signature.startswith("sha256="):
        raise HTTPException(401, "Invalid MONA Pay webhook signature")
    expected = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Invalid MONA Pay webhook signature")


def _transaction_payload(raw_body: bytes) -> dict:
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Invalid MONA Pay webhook JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid MONA Pay webhook payload")
    code = payload.get("transaction_code")
    amount = payload.get("amount")
    if (not isinstance(code, str) or not code.strip() or len(code) > 100
            or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0
            or not isinstance(payload.get("transfer_date"), str) or not payload["transfer_date"].strip()
            or not isinstance(payload.get("bank_name"), str) or not payload["bank_name"].strip()
            or payload.get("type") != "income"):
        raise HTTPException(422, "Incomplete or unsupported MONA Pay transaction")
    description = payload.get("description", "")
    if not isinstance(description, str) or len(description) > 2000:
        raise HTTPException(422, "Invalid MONA Pay transaction description")
    return {
        "transaction_code": code.strip(),
        "amount": amount,
        "description": description,
        "transfer_date": payload["transfer_date"][:40],
        "bank_name": payload["bank_name"][:100],
        "transaction_type": payload["type"],
        "is_sandbox": payload.get("is_sandbox") is True or code == "DUMMY123" or code.startswith("SANDBOX"),
    }


def _same_transaction(existing: MonaIncomingTransaction, values: dict) -> bool:
    return all(getattr(existing, key) == value for key, value in values.items())


def receive_transaction(db: Session, raw_body: bytes, timestamp: str, signature: str) -> dict:
    verify_signature(raw_body, timestamp, signature, settings.MONAPAY_WEBHOOK_SECRET)
    values = _transaction_payload(raw_body)
    existing = db.scalar(select(MonaIncomingTransaction).where(
        MonaIncomingTransaction.transaction_code == values["transaction_code"]))
    if existing:
        if not _same_transaction(existing, values):
            raise HTTPException(409, "MONA Pay transaction code was reused with different data")
        return {"accepted": True, "duplicate": True}

    db.add(MonaIncomingTransaction(**values))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(MonaIncomingTransaction).where(
            MonaIncomingTransaction.transaction_code == values["transaction_code"]))
        if existing and _same_transaction(existing, values):
            return {"accepted": True, "duplicate": True}
        raise HTTPException(409, "Concurrent MONA Pay transaction conflict")
    return {"accepted": True, "duplicate": False}
