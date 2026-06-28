"""Middleware to populate per-request logging and audit context."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp
from typing_extensions import override

from eneo.authentication.api_key_request_context import resolve_client_ip
from eneo.main.config import get_settings
from eneo.main.request_context import clear_request_context, set_request_context


def _current_trace_id() -> str | None:
    """Return the active OTEL trace_id as a 32-char hex string, or None."""
    try:
        from opentelemetry import trace as _otel_trace

        ctx = _otel_trace.get_current_span().get_span_context()
        if ctx.is_valid:
            return format(ctx.trace_id, "032x")
    except Exception:
        # Trace correlation must never break request handling — if the OTEL
        # SDK is in an unexpected state, fall back to no trace_id.
        pass
    return None


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Populate per-request logging and audit context in contextvars.

    Sets ``trace_id`` (from the active OTEL span) and ``correlation_id``
    (alias for trace_id, kept for backward compat) so that all log records
    emitted during the request carry both IDs.

    X-Trace-Id / X-Correlation-ID response headers are injected by the
    pure-ASGI TraceIdResponseMiddleware which runs at the ASGI level where
    the server span is guaranteed to be active.
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    @override
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        clear_request_context()

        # trace_id comes from the OTEL span created by the outer OTEL middleware
        trace_id = _current_trace_id()

        # Legacy header: honour x-correlation-id / x-request-id from callers.
        # Falls back to trace_id so correlation_id always equals trace_id when
        # a span is active.
        legacy_id = request.headers.get("x-correlation-id") or request.headers.get(
            "x-request-id"
        )
        correlation_id = trace_id or legacy_id

        settings = get_settings()
        ip_address = resolve_client_ip(
            request,
            trusted_proxy_count=settings.trusted_proxy_count,
            trusted_proxy_headers=settings.trusted_proxy_headers,
        )
        user_agent = request.headers.get("user-agent")

        request_id_raw = request.headers.get("x-request-id") or request.headers.get(
            "x-correlation-id"
        )
        request_id: UUID | None = None
        if request_id_raw:
            try:
                request_id = UUID(request_id_raw)
            except ValueError:
                request_id = None

        set_request_context(
            trace_id=trace_id,
            correlation_id=correlation_id,
            path=request.url.path,
            method=request.method,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
        )

        try:
            response = await call_next(request)
        finally:
            clear_request_context()

        return response
