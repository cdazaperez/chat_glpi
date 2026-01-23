"""
API middleware for Helpdesk AI.
Includes rate limiting, CORS, and request logging.
"""
import time
from collections import defaultdict
from typing import Callable, Dict, Tuple
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.logging import get_logger, set_correlation_id, get_correlation_id, StructuredLogger

# Use lazy logger initialization to ensure StructuredLogger is used
_logger: StructuredLogger = None


def _get_logger() -> StructuredLogger:
    """Get the logger instance, creating it lazily."""
    global _logger
    if _logger is None:
        _logger = get_logger(__name__)
    return _logger


class RateLimiter:
    """
    Simple in-memory rate limiter.

    For production, consider using Redis-based rate limiting.
    """

    def __init__(self, requests_per_minute: int = 30):
        self.rpm = requests_per_minute
        self.requests: Dict[str, list] = defaultdict(list)

    def _get_client_id(self, request: Request) -> str:
        """Get client identifier from request."""
        # Try to get from X-Forwarded-For header (behind proxy)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

        # Fall back to direct client IP
        if request.client:
            return request.client.host

        return "unknown"

    def is_rate_limited(self, request: Request) -> Tuple[bool, int]:
        """
        Check if request should be rate limited.

        Returns:
            Tuple of (is_limited, retry_after_seconds)
        """
        client_id = self._get_client_id(request)
        current_time = time.time()
        window_start = current_time - 60  # 1 minute window

        # Clean old requests
        self.requests[client_id] = [
            t for t in self.requests[client_id] if t > window_start
        ]

        # Check limit
        if len(self.requests[client_id]) >= self.rpm:
            oldest = min(self.requests[client_id])
            retry_after = int(oldest + 60 - current_time) + 1
            return True, max(retry_after, 1)

        # Record request
        self.requests[client_id].append(current_time)
        return False, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware for rate limiting requests."""

    def __init__(self, app, requests_per_minute: int = 30):
        super().__init__(app)
        self.limiter = RateLimiter(requests_per_minute)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for health checks
        if request.url.path in ["/health", "/health/ready", "/metrics"]:
            return await call_next(request)

        is_limited, retry_after = self.limiter.is_rate_limited(request)

        if is_limited:
            _get_logger().warning(
                "Rate limit exceeded",
                data={
                    "client": request.client.host if request.client else "unknown",
                    "path": request.url.path,
                    "correlation_id": get_correlation_id(),
                }
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too many requests",
                    "detail": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                    "retry_after": retry_after,
                    "correlation_id": get_correlation_id(),
                },
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware to add correlation ID to each request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get or generate correlation ID
        correlation_id = request.headers.get("X-Correlation-ID")
        correlation_id = set_correlation_id(correlation_id)

        # Process request
        response = await call_next(request)

        # Add correlation ID to response headers
        response.headers["X-Correlation-ID"] = correlation_id

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for logging requests and responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        # Log request
        _get_logger().info(
            "Request started",
            data={
                "method": request.method,
                "path": request.url.path,
                "client": request.client.host if request.client else "unknown",
            }
        )

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)

        # Log response
        log_data = {
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        }

        if response.status_code >= 400:
            _get_logger().warning("Request completed with error", data=log_data)
        else:
            _get_logger().info("Request completed", data=log_data)

        # Add timing header
        response.headers["X-Response-Time"] = f"{duration_ms}ms"

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Only add CSP for HTML responses
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "font-src 'self'; "
                "connect-src 'self'"
            )

        return response
