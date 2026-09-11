"""Safe, observable retry policy for outbound channel API calls."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

import httpx

from app.services.meta_errors import MetaAPIError
from app.services.provider_circuit_breaker import ProviderCircuitBreaker, ProviderCircuitOpen


logger = logging.getLogger(__name__)
T = TypeVar("T")
_provider_breaker = ProviderCircuitBreaker()

# Retry only errors where the provider explicitly rejected the request before
# delivery (429/5xx) or the client could not establish a connection.  A read
# timeout is deliberately not retried automatically: the provider may already
# have delivered the message, and blind retries could duplicate it.
_RETRYABLE_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
_RETRYABLE_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)


def is_retryable_provider_error(error: Exception) -> bool:
    if isinstance(error, MetaAPIError):
        return error.meta_status in _RETRYABLE_HTTP_STATUSES
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in _RETRYABLE_HTTP_STATUSES
    return isinstance(error, _RETRYABLE_TRANSPORT_ERRORS)


def run_with_provider_retry(
    *,
    provider: str,
    operation: str,
    request: Callable[[], T],
    max_attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    circuit_breaker: ProviderCircuitBreaker | None = None,
) -> T:
    """Run a provider call with bounded exponential retry and safe logging.

    Logs identify the provider and operation but intentionally exclude request
    bodies, URLs and exception text, which may contain customer data or tokens.
    """
    attempts = max(1, min(int(max_attempts), 5))
    breaker = circuit_breaker or _provider_breaker
    for attempt in range(1, attempts + 1):
        try:
            breaker.before_call(provider)
            result = request()
            breaker.record_success(provider)
            return result
        except ProviderCircuitOpen:
            raise
        except Exception as error:
            retryable = is_retryable_provider_error(error)
            logger.warning(
                "Channel provider request failed: provider=%s operation=%s "
                "attempt=%s/%s retryable=%s error_type=%s",
                provider,
                operation,
                attempt,
                attempts,
                retryable,
                type(error).__name__,
            )
            if retryable:
                breaker.record_failure(provider)
            if not retryable or attempt >= attempts:
                raise
            sleep(min(2.0, 0.25 * (2 ** (attempt - 1))))

    raise RuntimeError("Unreachable provider retry state")
