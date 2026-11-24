"""请求追踪、访问日志与 Prometheus 指标。"""

import logging
import time
import uuid

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.context import request_id_ctx
from app.core.metrics import metrics
from app.core.rate_limit import SlidingWindowLimiter

logger = logging.getLogger("app.http")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}

auth_limiter = SlidingWindowLimiter(settings.auth_rate_limit_per_minute, 60.0)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            blocked = False
            retry_after = 0
            auth_paths = {
                f"{settings.api_prefix}/auth/login",
                f"{settings.api_prefix}/auth/register",
            }
            if settings.auth_rate_limit_enabled and request.url.path in auth_paths:
                forwarded = request.headers.get(
                    "X-Forwarded-For"
                ) or request.headers.get("X-Real-IP", "")
                client_ip = (
                    forwarded.split(",")[0].strip()
                    if forwarded
                    else (request.client.host if request.client else "unknown")
                )
                allowed, retry_after = auth_limiter.allow(
                    f"{client_ip}:{request.url.path}"
                )
                blocked = not allowed

            if blocked:
                response = JSONResponse(
                    status_code=429,
                    content={
                        "code": 42900,
                        "message": f"请求过于频繁，请 {retry_after} 秒后重试",
                        "data": None,
                    },
                    headers={"Retry-After": str(retry_after)},
                )
            else:
                response = await call_next(request)

            status_code = response.status_code
            duration = time.perf_counter() - started
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time-Ms"] = f"{duration * 1000:.1f}"
            for header, value in SECURITY_HEADERS.items():
                response.headers.setdefault(header, value)
            return response
        finally:
            duration = time.perf_counter() - started
            if settings.metrics_enabled and request.url.path != "/metrics":
                metrics.observe_http(
                    request.method, request.url.path, status_code, duration
                )
            logger.info(
                "http_request method=%s path=%s status=%s duration_ms=%.1f",
                request.method,
                request.url.path,
                status_code,
                duration * 1000,
            )
            request_id_ctx.reset(token)
