import json
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.secret_manager import load_file_secrets, load_runtime_secrets
from app.services.channel_credentials import decrypt_token, encrypt_token

_rotation_spec = importlib.util.spec_from_file_location(
    "rotate_channel_secrets",
    Path(__file__).parents[1] / "scripts" / "rotate_channel_secrets.py",
)
_rotation_module = importlib.util.module_from_spec(_rotation_spec)
assert _rotation_spec.loader is not None
_rotation_spec.loader.exec_module(_rotation_module)
_rotate_nested = _rotation_module._rotate_nested


def _test_secret_path() -> Path:
    return Path(__file__).parents[1] / "test_data" / f"runtime-secrets-{uuid4().hex}.json"


def test_file_secret_manager_loads_only_known_scalar_fields():
    path = _test_secret_path()
    try:
        path.write_text(
            json.dumps({"AUTH_SECRET": "new-auth", "REDIS_URL": "redis://redis:6379/0", "UNKNOWN": "ignored"}),
            encoding="utf-8",
        )
        values = load_file_secrets(str(path), allowed_keys={"AUTH_SECRET", "REDIS_URL"})
        assert values == {"AUTH_SECRET": "new-auth", "REDIS_URL": "redis://redis:6379/0"}
    finally:
        path.unlink(missing_ok=True)


def test_file_secret_manager_rejects_non_scalar_values():
    path = _test_secret_path()
    try:
        path.write_text(json.dumps({"AUTH_SECRET": ["not-a-secret-string"]}), encoding="utf-8")
        with pytest.raises(ValueError, match="scalar"):
            load_runtime_secrets(allowed_keys={"AUTH_SECRET"}, mode="file", path=str(path))
    finally:
        path.unlink(missing_ok=True)


def test_file_secret_manager_normalizes_keys_and_ignores_unknown_fields():
    path = _test_secret_path()
    try:
        path.write_text(
            json.dumps({"auth_secret": "new-auth", "untrusted_key": "ignored"}),
            encoding="utf-8",
        )
        values = load_file_secrets(str(path), allowed_keys={"AUTH_SECRET"})
        assert values == {"AUTH_SECRET": "new-auth"}
    finally:
        path.unlink(missing_ok=True)


def test_secret_manager_rejects_invalid_json_and_unknown_mode_without_leaking_content():
    path = _test_secret_path()
    try:
        path.write_text('{"AUTH_SECRET":"private-value"', encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON") as invalid_json:
            load_runtime_secrets(
                allowed_keys={"AUTH_SECRET"}, mode="file", path=str(path)
            )
        assert "private-value" not in str(invalid_json.value)
        with pytest.raises(ValueError, match="must be env or file"):
            load_runtime_secrets(
                allowed_keys={"AUTH_SECRET"}, mode="remote-shell", path=str(path)
            )
    finally:
        path.unlink(missing_ok=True)


def test_nested_encrypted_values_are_rotated_without_printing_plaintext():
    old_key = "old-channel-encryption-key"
    new_key = "new-channel-encryption-key"
    encrypted = encrypt_token("oa-secret", old_key)
    rotated, count = _rotate_nested(
        {"provider": "zalo_oa", "oa_secret_key_encrypted": encrypted},
        old_key=old_key,
        new_key=new_key,
    )
    assert count == 1
    assert rotated["oa_secret_key_encrypted"] != encrypted
    assert decrypt_token(rotated["oa_secret_key_encrypted"], new_key) == "oa-secret"
