"""Pure-ASGI middleware that injects X-Trace-Id into every HTTP response.

Why a pure ASGI middleware instead of BaseHTTPMiddleware:
BaseHTTPMiddleware spawns an inner asyncio task for the inner app, creating
a context-copy boundary. A pure ASGI middleware intercepts the `send` callable
directly in the same context where the OTEL server span was created, so the
span is guaranteed to be active when `http.response.start` fires.

Middleware stack requirement: this middleware must be inside the OTEL FastAPI
middleware (OTEL must be the outermost wrapper). instrument_fastapi() adds OTEL
last — so anything added before it via app.add_middleware() will run inside the
OTEL context.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def current_trace_id() -> str | None:
    """Return the active OTEL trace_id as 32 hex chars, or None."""
    try:
        from opentelemetry import trace as _otel_trace

        ctx = _otel_trace.get_current_span().get_span_context()
        if ctx.is_valid:
            return format(ctx.trace_id, "032x")
    except Exception:
        # Trace-header injection runs on the response hot path; absence of a
        # trace_id is fine, but raising here would break the response.
        pass
    return None


class TraceIdResponseMiddleware:
    """Inject ``X-Trace-Id`` (and legacy ``X-Correlation-ID``) into every response.

    The active OTEL server span is guaranteed to exist here because this
    middleware runs inside the OTEL middleware wrapper. The header is set on
    ``http.response.start`` so it reaches the client on every status code,
    including 4xx and 5xx error responses.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_trace_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                trace_id = current_trace_id()
                if trace_id:
                    headers = MutableHeaders(scope=message)
                    # Only set if not already present (error handlers may set them)
                    if "x-trace-id" not in headers:
                        headers.append("X-Trace-Id", trace_id)
                    if "x-correlation-id" not in headers:
                        headers.append("X-Correlation-ID", trace_id)
            await send(message)

        await self.app(scope, receive, send_with_trace_id)
