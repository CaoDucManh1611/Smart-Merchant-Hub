"""Small in-process API-key pool with cooldowns for provider throttling."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

from app.services.provider_circuit_breaker import ProviderCircuitBreaker, ProviderCircuitOpen


class ApiKeyPoolUnavailable(RuntimeError):
    """Raised when no configured key can be used for the current attempt."""


_provider_breaker = ProviderCircuitBreaker()


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
    "quota",
    "rate limit",
    "rate_limit",
    "resource_exhausted",
    "too many requests",
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


def call_with_key_rotation(
    pool: ApiKeyPool,
    operation,
    *,
    provider: str = "ai",
    circuit_breaker: ProviderCircuitBreaker | None = None,
):
    """Run an operation and retry once with a different key on transient errors."""

    attempted: set[str] = set()
    last_error: Exception | None = None
    breaker = circuit_breaker or _provider_breaker
    # Walk the configured pool so a temporary quota/auth failure on one key
    # can fall through all remaining keys (the release profile uses five).
    max_attempts = pool.snapshot()["key_count"]
    if max_attempts <= 0:
        raise ApiKeyPoolUnavailable("Không có API key cho provider đang chọn.")
    for _ in range(max_attempts):
        try:
            key = pool.next_key(exclude=attempted)
        except ApiKeyPoolUnavailable:
            if last_error is not None:
                raise last_error
            raise
        attempted.add(key)
        try:
            breaker.before_call(provider)
            result = operation(key)
            breaker.record_success(provider)
            return result
        except ProviderCircuitOpen:
            raise
        except Exception as error:
            last_error = error
            pool.report_failure(key, error)
            if is_retryable_provider_error(error):
                breaker.record_failure(provider)
            if not is_retryable_provider_error(error) or len(attempted) >= max_attempts:
                raise
    raise last_error or ApiKeyPoolUnavailable("Không có API key cho provider đang chọn.")
