"""Normalization and privacy helpers for customer data collection."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from cryptography.fernet import InvalidToken

from app.core.config import settings
from app.services.channel_credentials import decrypt_token, encrypt_token


def _secret() -> bytes:
    value = (settings.CHANNEL_ENCRYPTION_KEY or settings.AUTH_SECRET or settings.APP_NAME).strip()
    return value.encode("utf-8")


def normalize_contact(kind: str, value: str) -> str:
    text = str(value or "").strip()
    if kind == "email":
        return text.casefold()
    if kind == "phone":
        digits = re.sub(r"\D+", "", text)
        if digits.startswith("84"):
            return "+" + digits
        if digits.startswith("0"):
            return "+84" + digits[1:]
        return "+" + digits if digits else ""
    raise ValueError("Unsupported contact kind")


def contact_hash(kind: str, value: str) -> str:
    normalized = normalize_contact(kind, value)
    if not normalized:
        raise ValueError("Contact value is empty after normalization")
    return hmac.new(_secret(), f"{kind}:{normalized}".encode("utf-8"), hashlib.sha256).hexdigest()


def encrypt_contact(kind: str, value: str) -> str:
    return encrypt_token(normalize_contact(kind, value), _secret().decode("utf-8"))


def decrypt_contact(kind: str, value_encrypted: str) -> str:
    """Decrypt a contact only for an already-authorized, tenant-scoped read."""
    value = decrypt_token(value_encrypted, _secret().decode("utf-8"))
    return normalize_contact(kind, value)


def customer_email_for_delivery(db, *, business_id: int, customer_id: int) -> str | None:
    """Read a tenant-owned email for a requested CRM delivery."""
    from app.models.customer import Customer
    from app.models.customer_collection import CustomerContact

    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.business_id == business_id,
    ).first()
    if customer is None:
        return None
    if customer.email and "@" in customer.email:
        return normalize_contact("email", customer.email)
    contacts = db.query(CustomerContact).filter(
        CustomerContact.business_id == business_id,
        CustomerContact.customer_id == customer_id,
        CustomerContact.kind == "email",
    ).order_by(CustomerContact.is_primary.desc(), CustomerContact.id.asc()).all()
    for contact in contacts:
        try:
            return decrypt_contact("email", contact.value_encrypted)
        except (InvalidToken, ValueError, TypeError):
            continue
    return None


def mask_contact(kind: str, value: str) -> str:
    normalized = normalize_contact(kind, value)
    if kind == "email":
        local, _, domain = normalized.partition("@")
        if not domain:
            return "***"
        return f"{(local[:1] or '*')}***@{domain}"
    if len(normalized) <= 4:
        return "***"
    return "*" * max(0, len(normalized) - 4) + normalized[-4:]


def generate_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_verification_code(code: str) -> str:
    return hmac.new(_secret(), str(code).encode("utf-8"), hashlib.sha256).hexdigest()
