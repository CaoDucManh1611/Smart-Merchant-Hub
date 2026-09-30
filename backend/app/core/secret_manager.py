"""Small secret-manager boundary for local, Docker and orchestrated deploys.

Production deployments can inject secrets as environment variables (the
default) or mount a JSON secret file and set ``SECRET_MANAGER_MODE=file``.
The application never logs the loaded values; this module only returns keys
that are known configuration fields.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping


def load_file_secrets(path: str, *, allowed_keys: set[str]) -> dict[str, str]:
    """Load a mounted JSON secret object while rejecting unknown fields."""
    secret_path = Path(str(path or "").strip()).expanduser()
    if not str(secret_path):
        raise ValueError("SECRET_MANAGER_FILE is required when file mode is enabled")
    if not secret_path.is_file():
        raise FileNotFoundError("SECRET_MANAGER_FILE does not exist")
    try:
        payload = json.loads(secret_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("SECRET_MANAGER_FILE is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("SECRET_MANAGER_FILE must contain a JSON object")
    values: dict[str, str] = {}
    for key, value in payload.items():
        normalized = str(key).strip().upper()
        if normalized not in allowed_keys:
            continue
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            raise ValueError(f"Secret value for {normalized} must be scalar")
        values[normalized] = str(value)
    return values


def load_runtime_secrets(*, allowed_keys: set[str], mode: str, path: str) -> dict[str, str]:
    """Return secret-manager overrides without exposing their contents."""
    normalized_mode = str(mode or "env").strip().lower()
    if normalized_mode in {"env", "environment", "injected"}:
        return {}
    if normalized_mode in {"file", "json", "mounted_file"}:
        return load_file_secrets(path, allowed_keys=allowed_keys)
    if normalized_mode in {"disabled", "none"}:
        return {}
    raise ValueError("SECRET_MANAGER_MODE must be env or file")


def secret_manager_mode_from_environment(default: str = "env") -> str:
    """Read the mode before Pydantic settings are constructed."""
    return os.getenv("SECRET_MANAGER_MODE", default)
