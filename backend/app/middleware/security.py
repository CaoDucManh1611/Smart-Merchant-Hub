"""Small, dependency-free HTTP security middleware."""

from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-process sliding-window limiter for API requests.

    This is intentionally dependency-free and protects a single backend
    process. Multi-replica production deployments should enforce the same
    policy at the reverse proxy or use a shared Redis limiter as well.
    """

    def __init__(
        self,
        app,
        *,
        enabled: bool,
        max_requests: int,
        window_seconds: int,
        trusted_proxy: bool = False,
    ):
        super().__init__(app)
        self.enabled = enabled
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(1, int(window_seconds))
        self.trusted_proxy = bool(trusted_proxy)
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

        now = monotonic()
        key = self._key(request)
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

