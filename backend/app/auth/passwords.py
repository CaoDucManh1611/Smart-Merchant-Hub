"""Small dependency-free password hashing helper."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets


ITERATIONS = 310_000
PASSWORD_MIN_LENGTH = 12
_COMMON_PASSWORDS = {
    "password",
    "password123",
    "123456789012",
    "qwertyuiop12",
    "adminadmin12",
}


def validate_password_strength(password: str) -> str:
    """Validate passwords accepted at user-facing account creation boundaries.

    Existing hashes may still be verified for backwards compatibility.  New
    passwords must be long enough and contain at least three character
    classes, while whitespace-only separators are rejected.
    """

    if not isinstance(password, str):
        raise ValueError("Mật khẩu phải là chuỗi ký tự.")
    value = password.strip()
    if value != password:
        raise ValueError("Mật khẩu không được có khoảng trắng ở đầu hoặc cuối.")
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Mật khẩu phải có ít nhất {PASSWORD_MIN_LENGTH} ký tự.")
    if len(value) > 256:
        raise ValueError("Mật khẩu không được vượt quá 256 ký tự.")
    if any(character.isspace() for character in value):
        raise ValueError("Mật khẩu không được chứa khoảng trắng.")
    if value.casefold() in _COMMON_PASSWORDS:
        raise ValueError("Mật khẩu quá dễ đoán.")
    classes = sum(
        bool(pattern.search(value))
        for pattern in (
            re.compile(r"[a-z]"),
            re.compile(r"[A-Z]"),
            re.compile(r"\d"),
            re.compile(r"[^A-Za-z0-9]"),
        )
    )
    if classes < 3:
        raise ValueError("Mật khẩu cần có ít nhất 3 nhóm: chữ thường, chữ hoa, số hoặc ký tự đặc biệt.")
    return value


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("Mật khẩu phải có ít nhất 8 ký tự.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    enc = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
    return f"pbkdf2_sha256${ITERATIONS}${enc(salt)}${enc(digest)}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded or not encoded.startswith("pbkdf2_sha256$"):
        return False
    try:
        _, iterations, salt_value, digest_value = encoded.split("$", 3)
        salt = base64.urlsafe_b64decode(salt_value + "===")
        expected = base64.urlsafe_b64decode(digest_value + "===")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)
