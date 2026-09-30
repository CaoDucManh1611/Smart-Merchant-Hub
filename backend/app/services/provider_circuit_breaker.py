"""Small provider-level circuit breaker shared by outbound integrations."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable


class ProviderCircuitOpen(RuntimeError):
    """Raised before a provider call while its circuit is open."""


@dataclass
class _Circuit:
    failures: int = 0
    state: str = "closed"
    opened_at: float = 0.0


class ProviderCircuitBreaker:
    def __init__(self, *, failure_threshold: int = 5, recovery_timeout: int = 30, clock: Callable[[], float] | None = None):
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_timeout = max(1, int(recovery_timeout))
        self.clock = clock or time.monotonic
        self._circuits: dict[str, _Circuit] = {}
        self._lock = threading.Lock()

    def _get(self, provider: str) -> _Circuit:
        return self._circuits.setdefault(str(provider).strip().lower(), _Circuit())

    def before_call(self, provider: str) -> None:
        with self._lock:
            circuit = self._get(provider)
            if circuit.state == "open":
                if self.clock() - circuit.opened_at < self.recovery_timeout:
                    raise ProviderCircuitOpen(f"Provider circuit is open: {provider}")
                circuit.state = "half_open"

    def record_failure(self, provider: str) -> None:
        with self._lock:
            circuit = self._get(provider)
            if circuit.state == "half_open":
                circuit.state = "open"
                circuit.opened_at = self.clock()
                return
            circuit.failures += 1
            if circuit.failures >= self.failure_threshold:
                circuit.state = "open"
                circuit.opened_at = self.clock()

    def record_success(self, provider: str) -> None:
        with self._lock:
            circuit = self._get(provider)
            circuit.failures = 0
            circuit.state = "closed"
            circuit.opened_at = 0.0

    def state(self, provider: str) -> str:
        with self._lock:
            return self._get(provider).state

    def snapshot(self) -> dict[str, dict[str, int | float | str]]:
        with self._lock:
            return {
                provider: {"state": circuit.state, "failures": circuit.failures, "opened_at": circuit.opened_at}
                for provider, circuit in self._circuits.items()
            }
