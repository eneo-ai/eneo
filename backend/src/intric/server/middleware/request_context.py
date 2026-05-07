"""Middleware to populate per-request logging and audit context."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp
from typing_extensions import override

from intric.authentication.api_key_request_context import resolve_client_ip
from intric.main.config import get_settings
from intric.main.request_context import clear_request_context, set_request_context


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Ensure correlation, routing, and audit metadata are available per request."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    @override
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        clear_request_context()
        correlation_id = request.headers.get("x-correlation-id") or request.headers.get(
            "x-request-id"
        )

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

        if correlation_id and "x-correlation-id" not in response.headers:
            response.headers["X-Correlation-ID"] = correlation_id

        return response
