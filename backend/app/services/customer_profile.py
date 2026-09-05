"""Deterministic normalization and precedence for Customer 360 profiles."""

from __future__ import annotations

import re
from collections.abc import Mapping


_PLACEHOLDER_NAMES = {
    "anonymous",
    "facebook user",
    "instagram user",
    "telegram user",
    "unknown",
    "user",
    "khách hàng",
}


def normalize_name(value: object) -> str | None:
    text = " ".join(str(value or "").split())
    if not text or text.casefold() in _PLACEHOLDER_NAMES:
        return None
    return text[:255]


def normalize_email(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if not text or "@" not in text or any(char.isspace() for char in text):
        return None
    local, _, domain = text.partition("@")
    if not local or "." not in domain:
        return None
    return text[:255]


def normalize_phone(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if len(digits) < 7:
        return None
    return ("+" if plus else "") + digits[:40]


def normalize_avatar_url(value: object) -> str | None:
    text = str(value or "").strip()
    if text.startswith(("https://", "http://")):
        return text[:2048]
    return None


def _name_priority(value: str | None, *, source: str) -> int:
    if not value:
        return 0
    if source == "display_name":
        return 3
    if source == "name":
        return 2
    return 1


def select_name(
    *,
    existing: object,
    name: object = None,
    display_name: object = None,
    username: object = None,
) -> str | None:
    """Select ``display_name > name > username`` without placeholder churn."""
    candidates = (
        (normalize_name(display_name), "display_name"),
        (normalize_name(name), "name"),
        (normalize_name(username), "username"),
    )
    incoming, incoming_source = next(((value, source) for value, source in candidates if value), (None, ""))
    current = normalize_name(existing)
    if not incoming:
        return current
    current_priority = 2 if current else 0
    if _name_priority(incoming, source=incoming_source) >= current_priority:
        return incoming
    return current


def merge_profile(
    customer,
    *,
    name: object = None,
    display_name: object = None,
    username: object = None,
    email: object = None,
    phone: object = None,
    avatar_url: object = None,
) -> dict[str, dict[str, str | None]]:
    """Apply the stable profile policy and return changed fields.

    Names use ``display_name > name > username``. Email/phone are normalized
    and never replaced by blank/invalid values. Avatar URLs are updated only
    when a valid HTTP(S) URL is available.
    """
    changes: dict[str, dict[str, str | None]] = {}
    selected_name = select_name(
        existing=customer.name,
        name=name,
        display_name=display_name,
        username=username,
    )
    values = {
        "name": selected_name,
        "email": normalize_email(email) or normalize_email(customer.email),
        "phone": normalize_phone(phone) or normalize_phone(customer.phone),
        "avatar_url": normalize_avatar_url(avatar_url) or normalize_avatar_url(customer.avatar_url),
    }
    for field, next_value in values.items():
        previous = getattr(customer, field, None)
        if next_value and previous != next_value:
            setattr(customer, field, next_value)
            changes[field] = {"old": previous, "new": next_value}
    return changes


def profile_change_metadata(changes: Mapping[str, Mapping[str, object]]) -> dict:
    return {
        "fields": {
            field: {"old": values.get("old"), "new": values.get("new")}
            for field, values in changes.items()
        }
    }

