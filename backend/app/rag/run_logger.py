"""Persistent, one-record-per-run logging for RAG operations."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings


_write_lock = threading.Lock()
logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_path() -> Path:
    configured_path = Path(settings.RAG_LOG_FILE)
    if not configured_path.is_absolute():
        # Keep the default log beside the backend, regardless of the process cwd.
        configured_path = Path(__file__).resolve().parents[2] / configured_path
    return configured_path


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
            **fields,
        }
        self._finished = False

    @property
    def run_id(self) -> str:
        return self._record["run_id"]

    def update(self, **fields: Any) -> None:
        """Add final-run fields without logging raw prompts or answers."""
        self._record.update(fields)

    def finish(self, status: str = "success", **fields: Any) -> None:
        if self._finished:
            return

        self._record.update(fields)
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
                error=str(exc_value)[:1000],
            )
        elif not self._finished:
            self.finish()
        return False
