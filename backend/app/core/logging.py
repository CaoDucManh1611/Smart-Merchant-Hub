"""Central logging safeguards for production deployments."""

from __future__ import annotations

import logging
import re
import traceback


_SECRET_PATTERN = re.compile(
    r"(?i)(authorization|access[_-]?token|refresh[_-]?token|api[_-]?key|"
    r"client[_-]?secret|app[_-]?secret|channel[_-]?encryption[_-]?key|"
    r"auth[_-]?secret|password|passwd|secret|database[_-]?url|"
    r"webhook[_-]?(?:secret|token)|facebook[_-]?page[_-]?access[_-]?token)"
    r"(['\"]?)(\s*[=:]\s*)(?:(?:Bearer|Token)\s+)?(['\"]?)([^'\"\s,;}]+)\4",
)


def redact_secrets(value: object) -> str:
    """Return a log-safe representation without exposing credential values."""
    # Keep an optional JSON quote around the replacement.  Besides being more
    # readable, this means a structured log line remains valid JSON after its
    # credential value has been removed.
    return _SECRET_PATTERN.sub(r"\1\2\3\4[REDACTED]\4", str(value))


class RedactingFilter(logging.Filter):
    """Redact both %-formatted and already-rendered log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Rendering first also covers ``logger.info("... %s", token)``.
            record.msg = redact_secrets(record.getMessage())
            record.args = ()
            # ``Formatter`` appends exception text after ``getMessage()``.
            # Replace it here as well so ``logger.exception(...)`` cannot
            # bypass redaction through an HTTP/provider error body.
            if record.exc_info:
                record.exc_text = redact_secrets(
                    "".join(traceback.format_exception(*record.exc_info))
                )
                record.exc_info = None
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
