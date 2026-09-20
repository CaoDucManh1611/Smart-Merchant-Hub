"""Small dependency-free password hashing helper."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


ITERATIONS = 310_000
SIGNUP_PASSWORD_MIN_LENGTH = 12


def validate_signup_password(password: str) -> str:
    """Validate the stronger policy used when a shop owner signs up.

    Hashing remains compatible with existing accounts and fixtures: this
    policy is deliberately applied at account-creation boundaries rather than
    inside :func:`hash_password`.
    """

    if not isinstance(password, str) or len(password) < SIGNUP_PASSWORD_MIN_LENGTH:
        raise ValueError(f"Mật khẩu phải có ít nhất {SIGNUP_PASSWORD_MIN_LENGTH} ký tự.")

    character_classes = (
        any(character.islower() for character in password),
        any(character.isupper() for character in password),
        any(character.isdigit() for character in password),
        any(not character.isalnum() and not character.isspace() for character in password),
    )
    if sum(character_classes) < 3:
        raise ValueError("Mật khẩu cần có ít nhất 3 trong 4 nhóm: chữ thường, chữ hoa, số và ký tự đặc biệt.")
    return password


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
