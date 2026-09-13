"""Small, dependency-free HTTP security middleware."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import logging
from threading import Lock
from time import monotonic

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add browser hardening headers when HTTPS is enabled."""

    def __init__(self, app, *, hsts_enabled: bool = False):
        super().__init__(app)
        self.hsts_enabled = hsts_enabled

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if self.hsts_enabled:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


class RateLimitBackendUnavailable(RuntimeError):
    """Raised when the shared rate-limit backend cannot be reached."""


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after: int
    reset_at: int


class RedisRateLimiter:
    """Atomic sliding-window limiter shared by every backend replica."""

    _SCRIPT = """
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local window_ms = tonumber(ARGV[2]) * 1000
local cutoff = now_ms - window_ms
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, cutoff)
local count = redis.call('ZCARD', KEYS[1])
local maximum = tonumber(ARGV[1])
if count >= maximum then
  local first = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local retry = window_ms
  if first[2] then retry = math.max(1, tonumber(first[2]) + window_ms - now_ms) end
  return {0, 0, retry, now_ms + window_ms}
end
local sequence = redis.call('INCR', KEYS[1] .. ':sequence')
local member = tostring(now_ms) .. ':' .. tostring(sequence)
redis.call('ZADD', KEYS[1], now_ms, member)
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]) + 2)
redis.call('EXPIRE', KEYS[1] .. ':sequence', tonumber(ARGV[2]) + 2)
return {1, maximum - count - 1, 0, now_ms + window_ms}
"""

    def __init__(self, redis_url: str, *, client=None, prefix: str = "crm:rate-limit:"):
        if not str(redis_url or "").strip() and client is None:
            raise ValueError("REDIS_URL is required for the Redis rate limiter")
        if client is None:
            try:
                import redis
                client = redis.Redis.from_url(str(redis_url), decode_responses=True)
            except Exception as exc:  # pragma: no cover - depends on deployment package
                raise RateLimitBackendUnavailable("Redis client is unavailable") from exc
        self.client = client
        self.prefix = str(prefix)

    @staticmethod
    def _key(client_key: str) -> str:
        digest = hashlib.sha256(str(client_key).encode("utf-8")).hexdigest()
        return digest

    def consume(self, client_key: str, *, max_requests: int, window_seconds: int) -> RateLimitDecision:
        key = self.prefix + self._key(client_key)
        try:
            result = self.client.eval(
                self._SCRIPT,
                1,
                key,
                int(max_requests),
                int(window_seconds),
            )
        except Exception as exc:
            raise RateLimitBackendUnavailable("Redis rate-limit backend is unavailable") from exc
        try:
            allowed, remaining, retry_ms, reset_at = [int(value) for value in result]
        except (TypeError, ValueError) as exc:
            raise RateLimitBackendUnavailable("Redis rate-limit response is invalid") from exc
        return RateLimitDecision(
            allowed=bool(allowed),
            remaining=max(0, remaining),
            retry_after=max(1, (retry_ms + 999) // 1000) if retry_ms else 0,
            reset_at=max(0, reset_at // 1000),
        )

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limiter for API requests.

    ``memory`` is a local development guard. Production may select the
    atomic shared ``redis`` backend, or delegate the primary limit to a
    trusted reverse proxy with ``proxy`` while retaining this guard.
    """

    def __init__(
        self,
        app,
        *,
        enabled: bool,
        max_requests: int,
        window_seconds: int,
        trusted_proxy: bool = False,
        backend: str = "memory",
        redis_url: str = "",
        redis_client=None,
    ):
        super().__init__(app)
        self.enabled = enabled
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(1, int(window_seconds))
        self.trusted_proxy = bool(trusted_proxy)
        self.backend = str(backend or "memory").strip().lower()
        self._redis = None
        if self.enabled and self.backend == "redis":
            self._redis = RedisRateLimiter(redis_url, client=redis_client)
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    @staticmethod
    def _client_key(request: Request) -> str:
        # Do not trust X-Forwarded-For unless the deployment's proxy is
        # explicitly configured to overwrite it.
        return request.client.host if request.client else "unknown"

    def _key(self, request: Request) -> str:
        if self.trusted_proxy:
            forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
            if forwarded:
                return forwarded
        return self._client_key(request)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.enabled or request.method == "OPTIONS" or not request.url.path.startswith("/api"):
            return await call_next(request)

        key = self._key(request)
        if self.backend == "redis":
            try:
                decision = self._redis.consume(
                    key,
                    max_requests=self.max_requests,
                    window_seconds=self.window_seconds,
                )
            except RateLimitBackendUnavailable:
                # Failing closed avoids silently removing the shared guard
                # during a Redis outage. Health probes remain available.
                response = JSONResponse(
                    {"detail": "Bộ giới hạn yêu cầu tạm thời không khả dụng."},
                    status_code=503,
                    headers={"Retry-After": "5"},
                )
                response.headers["X-RateLimit-Limit"] = str(self.max_requests)
                response.headers["X-RateLimit-Remaining"] = "0"
                return response
            if not decision.allowed:
                response = JSONResponse(
                    {"detail": "Quá nhiều yêu cầu, vui lòng thử lại sau."},
                    status_code=429,
                    headers={"Retry-After": str(decision.retry_after)},
                )
                response.headers["X-RateLimit-Limit"] = str(self.max_requests)
                response.headers["X-RateLimit-Remaining"] = "0"
                response.headers["X-RateLimit-Reset"] = str(decision.reset_at)
                return response
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(self.max_requests)
            response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
            response.headers["X-RateLimit-Reset"] = str(decision.reset_at)
            return response

        now = monotonic()
        with self._lock:
            bucket = self._requests[key]
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                retry_after = max(1, int(bucket[0] + self.window_seconds - now) + 1)
                response = JSONResponse(
                    {"detail": "Quá nhiều yêu cầu, vui lòng thử lại sau."},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )
                response.headers["X-RateLimit-Limit"] = str(self.max_requests)
                response.headers["X-RateLimit-Remaining"] = "0"
                return response
            bucket.append(now)
            remaining = max(0, self.max_requests - len(bucket))

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(now + self.window_seconds))
        return response

