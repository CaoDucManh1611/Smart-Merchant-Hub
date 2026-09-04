"""Small dependency-free password hashing helper."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


ITERATIONS = 310_000


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
