"""Central logging safeguards for production deployments."""

from __future__ import annotations

import logging
import re


_SECRET_PATTERN = re.compile(
    r"(?i)(authorization|access[_-]?token|refresh[_-]?token|api[_-]?key|"
    r"client[_-]?secret|app[_-]?secret|channel[_-]?encryption[_-]?key|"
    r"auth[_-]?secret|password|passwd|secret|database[_-]?url|"
    r"webhook[_-]?(?:secret|token)|facebook[_-]?page[_-]?access[_-]?token)"
    r"(\s*[=:]\s*)(?:(?:Bearer|Token)\s+)?(['\"]?)([^'\"\s,;}]+)\3",
)


def redact_secrets(value: object) -> str:
    """Return a log-safe representation without exposing credential values."""
    return _SECRET_PATTERN.sub(r"\1\2[REDACTED]", str(value))


class RedactingFilter(logging.Filter):
    """Redact both %-formatted and already-rendered log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Rendering first also covers ``logger.info("... %s", token)``.
            record.msg = redact_secrets(record.getMessage())
            record.args = ()
        except Exception:
            # Logging must never take down a request because a third-party
            # logger supplied an unusual object.
            record.msg = "[REDACTED_LOG_RECORD]"
            record.args = ()
        return True


def configure_logging() -> None:
    """Attach the filter to all currently configured application handlers."""
    redactor = RedactingFilter()
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO)
    for handler in root.handlers:
        if not any(isinstance(item, RedactingFilter) for item in handler.filters):
            handler.addFilter(redactor)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "app"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, RedactingFilter) for item in logger.filters):
            logger.addFilter(redactor)
