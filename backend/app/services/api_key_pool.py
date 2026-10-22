"""Small in-process API-key pool with cooldowns for provider throttling."""

from __future__ import annotations

import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

from app.services.provider_circuit_breaker import ProviderCircuitBreaker, ProviderCircuitOpen


class ApiKeyPoolUnavailable(RuntimeError):
    """Raised when no configured key can be used for the current attempt."""


_provider_breaker = ProviderCircuitBreaker()
_provider_semaphores: dict[str, threading.BoundedSemaphore] = {}
_provider_semaphores_lock = threading.Lock()
_MAX_PROVIDER_CONCURRENCY = 4
_MAX_PROVIDER_ATTEMPTS = 3


_TRANSIENT_MARKERS = (
    "401",
    "403",
    "429",
    "500",
    "502",
    "503",
    "504",
    "authentication",
    "invalid api key",
    "invalid_api_key",
    "unauthorized",
    "forbidden",
    "permission denied",
    "quota",
    "rate limit",
    "rate_limit",
    "resource_exhausted",
    "too many requests",
    "timeout",
    "timed out",
    "connection reset",
    "connection error",
    "connection refused",
    "server disconnected",
    "temporarily unavailable",
)


def is_retryable_provider_error(error: Exception) -> bool:
    """Classify provider failures without depending on one SDK exception type."""

    message = str(error).lower()
    return any(marker in message for marker in _TRANSIENT_MARKERS)


@dataclass
class _KeyState:
    key: str
    cooldown_until: float = 0.0
    failures: int = 0


class ApiKeyPool:
    """Round-robin key selection with process-local failure cooldowns."""

    def __init__(
        self,
        keys: list[str],
        *,
        cooldown_seconds: int = 60,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._keys = [_KeyState(key=value.strip()) for value in keys if value and value.strip()]
        self._keys = list({item.key: item for item in self._keys}.values())
        self._cooldown_seconds = max(1, int(cooldown_seconds))
        self._clock = clock or time.monotonic
        self._cursor = 0
        self._lock = threading.Lock()

    def next_key(self, *, exclude: set[str] | None = None) -> str:
        excluded = exclude or set()
        with self._lock:
            if not self._keys:
                raise ApiKeyPoolUnavailable("Không có API key khả dụng.")
            now = self._clock()
            for offset in range(len(self._keys)):
                index = (self._cursor + offset) % len(self._keys)
                state = self._keys[index]
                if state.key in excluded or state.cooldown_until > now:
                    continue
                self._cursor = (index + 1) % len(self._keys)
                return state.key
            raise ApiKeyPoolUnavailable("Tất cả API key đang bị tạm ngưng hoặc đã bị loại khỏi lượt thử.")

    def report_failure(self, key: str, error: Exception) -> None:
        if not is_retryable_provider_error(error):
            return
        with self._lock:
            for state in self._keys:
                if state.key == key:
                    state.failures += 1
                    state.cooldown_until = self._clock() + self._cooldown_seconds
                    return

    def snapshot(self) -> dict:
        now = self._clock()
        with self._lock:
            return {
                "key_count": len(self._keys),
                "available_count": sum(1 for state in self._keys if state.cooldown_until <= now),
                "cooldown_seconds": self._cooldown_seconds,
                "keys": [
                    {
                        "index": index,
                        "available": state.cooldown_until <= now,
                        "failures": state.failures,
                    }
                    for index, state in enumerate(self._keys)
                ],
            }


def redact_provider_error(error: Exception) -> str:
    """Return a short safe error summary with credential-like values removed."""

    message = str(error)
    message = re.sub(r"(?i)(api[_ -]?key|token|secret)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", message)
    return message[:240]


def _provider_semaphore(provider: str) -> threading.BoundedSemaphore:
    name = str(provider).strip().lower() or "ai"
    with _provider_semaphores_lock:
        return _provider_semaphores.setdefault(name, threading.BoundedSemaphore(_MAX_PROVIDER_CONCURRENCY))


@contextmanager
def provider_request_slot(provider: str, *, timeout_seconds: float = 10):
    """Limit simultaneous calls per provider in this worker process."""
    semaphore = _provider_semaphore(provider)
    if not semaphore.acquire(timeout=max(0.0, timeout_seconds)):
        raise ApiKeyPoolUnavailable("Nhà cung cấp AI đang quá tải; yêu cầu được chuyển nhân viên hỗ trợ.")
    try:
        yield
    finally:
        semaphore.release()


async def acquire_provider_request_slot(provider: str, *, timeout_seconds: float = 10):
    """Acquire the same provider limit without blocking the async event loop."""
    import asyncio

    semaphore = _provider_semaphore(provider)
    acquired = await asyncio.to_thread(semaphore.acquire, True, max(0.0, timeout_seconds))
    if not acquired:
        raise ApiKeyPoolUnavailable("Nhà cung cấp AI đang quá tải; yêu cầu được chuyển nhân viên hỗ trợ.")
    return semaphore


def provider_call_started(provider: str) -> None:
    _provider_breaker.before_call(provider)


def provider_call_succeeded(provider: str) -> None:
    _provider_breaker.record_success(provider)


def provider_call_failed(provider: str, error: Exception) -> None:
    if is_retryable_provider_error(error):
        _provider_breaker.record_failure(provider)


def call_with_key_rotation(
    pool: ApiKeyPool,
    operation,
    *,
    provider: str = "ai",
    circuit_breaker: ProviderCircuitBreaker | None = None,
    failure_scope: str | None = None,
):
    """Run a provider call with bounded key rotation and a per-provider limit."""

    attempted: set[str] = set()
    last_error: Exception | None = None
    breaker = circuit_breaker or _provider_breaker
    scope = failure_scope or provider
    max_attempts = min(pool.snapshot()["key_count"], _MAX_PROVIDER_ATTEMPTS)
    if max_attempts <= 0:
        raise ApiKeyPoolUnavailable("Không có API key cho provider đang chọn.")
    with provider_request_slot(provider):
        for _ in range(max_attempts):
            try:
                key = pool.next_key(exclude=attempted)
            except ApiKeyPoolUnavailable:
                if last_error is not None:
                    raise last_error
                raise
            attempted.add(key)
            try:
                breaker.before_call(scope)
                result = operation(key)
                breaker.record_success(scope)
                return result
            except ProviderCircuitOpen:
                raise
            except Exception as error:
                last_error = error
                pool.report_failure(key, error)
                if is_retryable_provider_error(error):
                    breaker.record_failure(scope)
                if not is_retryable_provider_error(error) or len(attempted) >= max_attempts:
                    raise
    raise last_error or ApiKeyPoolUnavailable("Không có API key cho provider đang chọn.")
