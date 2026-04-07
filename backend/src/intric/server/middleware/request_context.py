"""Middleware to populate per-request logging context."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp
from typing_extensions import override

from intric.main.request_context import clear_request_context, set_request_context


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Ensure correlation and routing metadata are available in logs."""

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

        set_request_context(
            correlation_id=correlation_id,
            path=request.url.path,
            method=request.method,
        )

        try:
            response = await call_next(request)
        finally:
            clear_request_context()

        if correlation_id and "x-correlation-id" not in response.headers:
            response.headers["X-Correlation-ID"] = correlation_id

        return response
