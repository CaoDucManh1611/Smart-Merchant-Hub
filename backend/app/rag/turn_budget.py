"""Cooperative turn limits shared by LLM retries, routes and retrieval.

Context propagates through asyncio tasks/to_thread, not arbitrary thread pools.
SDK timeouts bound blocking I/O; this module cannot interrupt synchronous code.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import math
import re
import threading
import time


class TurnBudgetExceeded(RuntimeError):
    """A local limit was reached; never retry or penalize a provider/key."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Turn budget exhausted: {reason}")


_current: ContextVar["TurnBudget | None"] = ContextVar("llm_turn_budget", default=None)
_logical_depth: ContextVar[int] = ContextVar("llm_logical_depth", default=0)
_active_attempt: ContextVar[dict | None] = ContextVar("llm_physical_attempt", default=None)
_attempt_metadata: ContextVar[dict | None] = ContextVar("llm_attempt_metadata", default=None)


def _safe_error_token(value):
    if not isinstance(value, (str, int)):
        return None
    value = str(value)
    return value[:80] if re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value) else None


class TurnBudget:
    def __init__(self, timeout_seconds, max_calls, max_attempts, max_provider_switches, parent=None):
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        for name, value in (("max_calls", max_calls), ("max_attempts", max_attempts),
                            ("max_provider_switches", max_provider_switches)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        self.started_at = time.monotonic()
        self.deadline = self.started_at + timeout_seconds
        self.max_calls = max_calls
        self.max_attempts = max_attempts
        self.max_provider_switches = max_provider_switches
        self.calls = self.attempts = self.provider_switches = 0
        self.last_provider = None
        self._attempt_records = []
        self._parent = parent
        self._lock = parent._lock if parent else threading.RLock()
        if parent:
            self.deadline = min(self.deadline, parent.deadline)

    def _lineage(self):
        budget = self
        while budget is not None:
            yield budget
            budget = budget._parent

    def check_deadline(self):
        if time.monotonic() >= self.deadline:
            raise TurnBudgetExceeded("deadline")

    def _charge(self, provider=None):
        with self._lock:
            budgets = list(self._lineage())
            for budget in budgets:
                budget.check_deadline()
                if provider is None:
                    if budget.calls >= budget.max_calls:
                        raise TurnBudgetExceeded("max_calls")
                else:
                    if budget.attempts >= budget.max_attempts:
                        raise TurnBudgetExceeded("max_attempts")
                    if (budget.last_provider not in (None, provider)
                            and budget.provider_switches >= budget.max_provider_switches):
                        raise TurnBudgetExceeded("max_provider_switches")
            # Check every enclosing limit before changing any counters.
            for budget in budgets:
                if provider is None:
                    budget.calls += 1
                else:
                    budget.attempts += 1
                    budget.provider_switches += budget.last_provider not in (None, provider)
                    budget.last_provider = provider

    def start_call(self):
        self._charge()

    def start_attempt(self, provider: str, model: str | None = None):
        with self._lock:
            provider = provider.strip().lower()
            self._charge(provider)
            record = {
                "provider": provider, "model": model,
                "started_at": time.monotonic(), "latency_ms": None,
                "outcome": "pending", "error_type": None, "status_code": None,
                "provider_error_code": None, "provider_error_param": None,
                "usage": None,
            }
            metadata = _attempt_metadata.get() or {}
            for field in ("llm_stage", "schema_name", "schema_fingerprint"):
                value = _safe_error_token(metadata.get(field))
                if value is not None:
                    record[field] = value
            for budget in self._lineage():
                budget._attempt_records.append(record)
            return record

    def finish_attempt(self, record, error=None):
        status_code = getattr(error, "status_code", None) if error else None
        try:
            status_code = int(status_code) if status_code is not None else None
        except (TypeError, ValueError):
            status_code = None
        with self._lock:
            record.update(
                latency_ms=max(0.0, (time.monotonic() - record["started_at"]) * 1000),
                outcome="error" if error else "success",
                error_type=type(error).__name__ if error else None,
                status_code=status_code,
                provider_error_code=_safe_error_token(getattr(error, "code", None)) if error else None,
                provider_error_param=_safe_error_token(getattr(error, "param", None)) if error else None,
            )

    def record_usage(self, provider: str, model: str, usage: dict | None, *, attempt=None):
        """Attach SDK-reported counts to this task's active physical attempt."""
        record = attempt if attempt is not None else _active_attempt.get()
        if record is None:
            return
        with self._lock:
            record["provider"], record["model"] = provider, model
            record["usage"] = dict(usage) if usage is not None else None

    def remaining_seconds(self, default: float) -> float:
        if not math.isfinite(default) or default <= 0:
            raise ValueError("default must be finite and positive")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TurnBudgetExceeded("deadline")
        return min(default, remaining)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "deadline": self.deadline,
                "remaining_seconds": max(0.0, self.deadline - time.monotonic()),
                "elapsed_seconds": max(0.0, time.monotonic() - self.started_at),
                "calls": self.calls, "max_calls": self.max_calls,
                "attempts": self.attempts, "max_attempts": self.max_attempts,
                "provider_switches": self.provider_switches,
                "max_provider_switches": self.max_provider_switches,
                "last_provider": self.last_provider,
                "attempt_records": [
                    {**record, "usage": dict(record["usage"]) if record["usage"] is not None else None}
                    for record in self._attempt_records
                ],
            }


@contextmanager
def turn_budget(timeout_seconds=30, max_calls=4, max_attempts=6, max_provider_switches=1):
    """Yield a fresh budget; nested scopes also charge every enclosing budget."""
    budget = TurnBudget(timeout_seconds, max_calls, max_attempts, max_provider_switches, _current.get())
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)


def current_budget() -> TurnBudget | None:
    return _current.get()


def remaining_seconds(default: float) -> float:
    """Clamp an existing timeout to the turn deadline; raise if expired."""
    budget = current_budget()
    return budget.remaining_seconds(default) if budget else default


@contextmanager
def physical_attempt(provider: str, model: str | None = None):
    budget = current_budget()
    if not budget:
        yield
        return
    record = budget.start_attempt(provider, model)
    token = _active_attempt.set(record)
    try:
        yield
        budget.check_deadline()
    except BaseException as error:
        budget.finish_attempt(record, error)
        raise
    else:
        budget.finish_attempt(record)
    finally:
        _active_attempt.reset(token)


@contextmanager
def attempt_context(**metadata):
    """Attach bounded, non-secret request metadata to physical attempt records."""
    allowed = {key: value for key, value in metadata.items()
               if key in {"llm_stage", "schema_name", "schema_fingerprint"}}
    token = _attempt_metadata.set(allowed)
    try:
        yield
    finally:
        _attempt_metadata.reset(token)


@contextmanager
def logical_call():
    """Count one caller request, not its nested provider wrappers or retries."""
    budget = current_budget()
    if budget:
        budget.check_deadline()
        if not _logical_depth.get():
            budget.start_call()
    token = _logical_depth.set(_logical_depth.get() + 1)
    try:
        yield
        if budget:
            budget.check_deadline()
    finally:
        _logical_depth.reset(token)


def budgeted_call(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with logical_call():
            return function(*args, **kwargs)
    return wrapped


def budgeted_stream(function):
    """Count at iteration time; never leave ContextVars set across a yield."""
    @wraps(function)
    async def wrapped(*args, **kwargs):
        budget = current_budget()
        depth = _logical_depth.get()
        if budget:
            budget.check_deadline()
            if not depth:
                budget.start_call()
        stream = function(*args, **kwargs)
        try:
            while True:
                token = _logical_depth.set(depth + 1)
                try:
                    chunk = await anext(stream)
                except StopAsyncIteration:
                    break
                finally:
                    _logical_depth.reset(token)
                if budget:
                    budget.check_deadline()
                yield chunk
            if budget:
                budget.check_deadline()
        finally:
            await stream.aclose()
    return wrapped
