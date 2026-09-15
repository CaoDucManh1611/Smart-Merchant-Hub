"""Persistent, one-record-per-run logging for RAG operations."""

from __future__ import annotations

import json
import hashlib
import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings


_write_lock = threading.Lock()
logger = logging.getLogger(__name__)

_SENSITIVE_ERROR = re.compile(
    r"(?i)(token|secret|authorization|api[_-]?key|password)\s*[=:]\s*[^\s,;]+"
)
_EMAIL = re.compile(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d .()-]{7,}\d)(?!\d)")
_PRIVATE_FIELDS = {
    "query_preview",
    "prompt",
    "answer",
    "content",
    "raw_payload",
    "message_body",
    "customer_text",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_path() -> Path:
    configured_path = Path(settings.RAG_LOG_FILE)
    if not configured_path.is_absolute():
        # Keep the default log beside the backend, regardless of the process cwd.
        configured_path = Path(__file__).resolve().parents[2] / configured_path
    return configured_path


def safe_error_message(error: Exception | str | None, *, limit: int = 500) -> str:
    """Return diagnostics without credentials or common customer identifiers."""
    message = str(error or "").strip()
    message = _SENSITIVE_ERROR.sub(r"\1=[redacted]", message)
    message = _EMAIL.sub("[email]", message)
    message = _PHONE.sub("[phone]", message)
    return message[:limit] or "RAG operation failed"


def query_metadata(value: Any) -> dict[str, Any]:
    query = str(value or "")
    return {
        "query_chars": len(query),
        "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest()[:16],
    }


def _safe_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop prompt/customer payloads from logs while retaining safe counters."""
    safe: dict[str, Any] = {}
    for key, value in fields.items():
        if key in _PRIVATE_FIELDS:
            if key == "query_preview":
                safe.update(query_metadata(value))
            continue
        if key == "error":
            safe[key] = safe_error_message(value, limit=500)
            continue
        safe[key] = value
    return safe


class RagRunLog:
    """Collect details and append exactly one JSON record when a run ends."""

    def __init__(self, operation: str, **fields: Any) -> None:
        self._started_monotonic = time.perf_counter()
        self._record: dict[str, Any] = {
            "run_id": uuid4().hex,
            "operation": operation,
            "status": "running",
            "started_at": _utc_now(),
            "provider": settings.LLM_PROVIDER,
            "model": settings.LLM_MODEL,
            "embedding_provider": settings.EMBEDDING_PROVIDER,
            "embedding_model": settings.EMBEDDING_MODEL,
            **_safe_fields(fields),
        }
        self._finished = False

    @property
    def run_id(self) -> str:
        return self._record["run_id"]

    def update(self, **fields: Any) -> None:
        """Add final-run fields without logging raw prompts or answers."""
        self._record.update(_safe_fields(fields))

    def finish(self, status: str = "success", **fields: Any) -> None:
        if self._finished:
            return

        self._record.update(_safe_fields(fields))
        self._record["status"] = status
        self._record["finished_at"] = _utc_now()
        self._record["duration_ms"] = round(
            (time.perf_counter() - self._started_monotonic) * 1000,
            2,
        )

        path = _log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with _write_lock:
                with path.open("a", encoding="utf-8") as log_file:
                    log_file.write(
                        json.dumps(
                            self._record,
                            ensure_ascii=False,
                            default=str,
                        )
                        + "\n"
                    )
        except Exception:
            # Observability must never break the user's RAG request.
            logger.exception("Could not write RAG run log to %s", path)
        finally:
            self._finished = True

    def __enter__(self) -> "RagRunLog":
        return self

    def __exit__(self, exc_type, exc_value, _traceback) -> bool:
        if exc_value is not None:
            self.finish(
                "error",
                error_type=exc_type.__name__ if exc_type else "Exception",
                error=safe_error_message(exc_value),
            )
        elif not self._finished:
            self.finish()
        return False
