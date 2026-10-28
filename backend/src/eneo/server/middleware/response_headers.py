"""Pure-ASGI middleware: the one owner of default response headers.

Every header here is a default, set only when the response did not set its
own, so endpoint and path policies win (the MCP view's CSP, icons and SSE keep
theirs; the module-login pages keep their Referrer-Policy).

- ``/api/`` responses: once the browser session cookie shares the API's
  origin, an API or file response must not be cached, sniffed or run as a
  document. They get ``Cache-Control: no-store``, ``X-Content-Type-Options:
  nosniff`` and a sandbox CSP.
- With the web app on, every other response on the host gets the browser
  headers Next sent on every route. The web app's pages carry their own CSP
  (``server/web_app.py``), whose ``frame-ancestors`` decides framing, so
  ``X-Frame-Options`` is not sent: one framing rule per response class.

Outside development both get HSTS; never conditioned on the request scheme,
which is http behind Traefik.

Pure ASGI, not BaseHTTPMiddleware: streaming, SSE and Range responses stay
unbuffered, and status, body and length headers are never touched.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_API_DEFAULTS = (
    ("cache-control", "no-store"),
    ("x-content-type-options", "nosniff"),
    ("content-security-policy", "default-src 'none'; frame-ancestors 'none'; sandbox"),
)
_WEB_APP_DEFAULTS = (
    ("x-content-type-options", "nosniff"),
    ("referrer-policy", "strict-origin-when-cross-origin"),
    ("x-dns-prefetch-control", "off"),
    ("permissions-policy", "camera=(), geolocation=(), microphone=(self)"),
)
_HSTS = ("strict-transport-security", "max-age=31536000")


class ResponseHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool, web_app: bool) -> None:
        self.app = app
        hsts_default = (_HSTS,) if hsts else ()
        self.api_defaults = (*_API_DEFAULTS, *hsts_default)
        self.other_defaults = (*_WEB_APP_DEFAULTS, *hsts_default) if web_app else ()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["path"].startswith("/api/"):
            defaults = self.api_defaults
        else:
            defaults = self.other_defaults
        if not defaults:
            await self.app(scope, receive, send)
            return

        async def send_with_defaults(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in defaults:
                    if name not in headers:
                        headers.append(name, value)
            await send(message)

        await self.app(scope, receive, send_with_defaults)
