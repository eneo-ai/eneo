"""Pure-ASGI middleware that gives /api/ responses safe defaults.

Once the browser session cookie shares the API's origin, an API or file
response must not be cached, sniffed or run as a document. Every response under
``/api/`` therefore gets ``Cache-Control: no-store``, ``X-Content-Type-Options:
nosniff`` and a sandbox CSP, each only when the endpoint did not set its own
(the MCP view, icons and SSE keep theirs). Outside development it also gets
HSTS; never conditioned on the request scheme, which is http behind Traefik.

Pure ASGI, not BaseHTTPMiddleware: streaming, SSE and Range responses stay
unbuffered, and status, body and length headers are never touched.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_DEFAULTS = (
    ("cache-control", "no-store"),
    ("x-content-type-options", "nosniff"),
    ("content-security-policy", "default-src 'none'; frame-ancestors 'none'; sandbox"),
)
_HSTS = ("strict-transport-security", "max-age=31536000")


class ApiResponseHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.defaults = (*_DEFAULTS, _HSTS) if hsts else _DEFAULTS

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return

        async def send_with_defaults(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.defaults:
                    if name not in headers:
                        headers.append(name, value)
            await send(message)

        await self.app(scope, receive, send_with_defaults)
