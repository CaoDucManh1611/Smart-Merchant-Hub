"""Encrypt/decrypt channel tokens before persistence or outbound use."""

import base64
import hashlib

from cryptography.fernet import Fernet


def _fernet(secret: str) -> Fernet:
    if not secret:
        raise ValueError("Channel encryption key is required")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_token(token: str, secret: str) -> str:
    return _fernet(secret).encrypt(token.encode()).decode()


def decrypt_token(ciphertext: str, secret: str) -> str:
    return _fernet(secret).decrypt(ciphertext.encode()).decode()
