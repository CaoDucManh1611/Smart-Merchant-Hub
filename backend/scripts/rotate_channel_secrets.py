"""Re-encrypt tenant secrets during CHANNEL_ENCRYPTION_KEY rotation.

The old key is read only from a protected environment variable so it never
appears in shell history or command-line process listings. The default is a
dry-run; ``--confirm`` is required after a verified database backup.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models.business import User
from app.models.channel import Channel
from app.models.customer_collection import CustomerContact, CustomerVerificationChallenge
from app.services.channel_credentials import decrypt_token, encrypt_token
from app.services.customer_collection import normalize_contact


def _rotate_nested(value: Any, *, old_key: str, new_key: str) -> tuple[Any, int]:
    if isinstance(value, dict):
        rotated: dict[str, Any] = {}
        count = 0
        for key, item in value.items():
            if str(key).endswith("_encrypted") and isinstance(item, str) and item != "[REDACTED]":
                rotated[key] = encrypt_token(decrypt_token(item, old_key), new_key)
                count += 1
            else:
                rotated_item, item_count = _rotate_nested(item, old_key=old_key, new_key=new_key)
                rotated[key] = rotated_item
                count += item_count
        return rotated, count
    if isinstance(value, list):
        rotated_list = []
        count = 0
        for item in value:
            rotated_item, item_count = _rotate_nested(item, old_key=old_key, new_key=new_key)
            rotated_list.append(rotated_item)
            count += item_count
        return rotated_list, count
    return value, 0


def _contact_hash(kind: str, value: str, key: str) -> str:
    normalized = normalize_contact(kind, value)
    return hmac.new(key.encode("utf-8"), f"{kind}:{normalized}".encode("utf-8"), hashlib.sha256).hexdigest()


def rotate_database_secrets(db, *, old_key: str, new_key: str, commit: bool) -> dict[str, int]:
    if not old_key or not new_key:
        raise ValueError("Both old and new encryption keys are required")
    if hmac.compare_digest(old_key, new_key):
        raise ValueError("Old and new encryption keys must differ")

    counts = {
        "channels": 0,
        "channel_config_values": 0,
        "mfa_secrets": 0,
        "contacts": 0,
        "otp_challenges_expired": 0,
    }
    channels = db.scalars(select(Channel).where(Channel.access_token_encrypted.is_not(None))).all()
    for channel in channels:
        channel.access_token_encrypted = encrypt_token(
            decrypt_token(channel.access_token_encrypted, old_key), new_key
        )
        counts["channels"] += 1
        if isinstance(channel.config, dict):
            channel.config, config_count = _rotate_nested(
                channel.config, old_key=old_key, new_key=new_key
            )
            counts["channel_config_values"] += config_count

    for user in db.scalars(select(User).where(User.mfa_secret_encrypted.is_not(None))).all():
        user.mfa_secret_encrypted = encrypt_token(
            decrypt_token(user.mfa_secret_encrypted, old_key), new_key
        )
        counts["mfa_secrets"] += 1

    for contact in db.scalars(select(CustomerContact)).all():
        plaintext = decrypt_token(contact.value_encrypted, old_key)
        contact.value_encrypted = encrypt_token(plaintext, new_key)
        contact.value_hash = _contact_hash(contact.kind, plaintext, new_key)
        counts["contacts"] += 1

    # The OTP code is intentionally stored only as a one-way hash, so it
    # cannot be re-encrypted. Expire outstanding challenges and let checkout
    # request a fresh code after the key rotation.
    pending = db.scalars(
        select(CustomerVerificationChallenge).where(
            CustomerVerificationChallenge.status.in_(("queued", "sent", "pending"))
        )
    ).all()
    if commit:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for challenge in pending:
            challenge.status = "expired"
            challenge.expires_at = now
            counts["otp_challenges_expired"] += 1
        db.commit()
    else:
        counts["otp_challenges_expired"] = len(pending)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate encrypted tenant credentials")
    parser.add_argument("--old-key-env", default="OLD_CHANNEL_ENCRYPTION_KEY")
    parser.add_argument("--new-key-env", default="CHANNEL_ENCRYPTION_KEY")
    parser.add_argument("--confirm", action="store_true", help="commit after a verified backup")
    args = parser.parse_args()

    old_key = os.getenv(args.old_key_env, "")
    new_key = os.getenv(args.new_key_env, "")
    if not old_key or not new_key:
        raise SystemExit("Old/new keys must be supplied through protected environment variables.")

    with SessionLocal() as db:
        counts = rotate_database_secrets(db, old_key=old_key, new_key=new_key, commit=args.confirm)
    print("Secret rotation plan: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    if not args.confirm:
        print("Dry-run only. Re-run with --confirm after a verified PostgreSQL backup.")
    else:
        print("Secret rotation committed. Deploy the new key before revoking the old one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
