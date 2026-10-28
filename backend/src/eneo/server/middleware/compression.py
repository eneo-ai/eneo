"""Gzip for text responses only, once, at level 6 (replaces Next's compress).

Starlette's GZipMiddleware would also compress downloads, Range responses and
every other type. This responder decides on ``http.response.start`` and passes
everything else through untouched, so downloads keep ``Content-Length``, SSE
stays unbuffered and 206 bodies stay byte-identical.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipMiddleware, GZipResponder
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Python 3.11 maps .js to application/javascript (text/javascript only from 3.12).
_COMPRESSIBLE = frozenset(
    {
        "application/json",
        "text/html",
        "text/javascript",
        "application/javascript",
        "text/css",
        "image/svg+xml",
    }
)


def _compressible(status: int, headers: Headers) -> bool:
    media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    return (
        status != 206
        and "content-encoding" not in headers
        and "content-disposition" not in headers
        and media_type in _COMPRESSIBLE
    )


class _SelectiveGZipResponder(GZipResponder):
    _passthrough = False

    async def send_with_compression(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self._passthrough = not _compressible(
                message["status"], Headers(raw=message["headers"])
            )
        if self._passthrough:
            await self.send(message)
            return
        await super().send_with_compression(message)


class SelectiveGZipMiddleware(GZipMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app, minimum_size=500, compresslevel=6)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and "gzip" in Headers(scope=scope).get(
            "accept-encoding", ""
        ):
            responder = _SelectiveGZipResponder(
                self.app, self.minimum_size, compresslevel=self.compresslevel
            )
            await responder(scope, receive, send)
            return
        await self.app(scope, receive, send)
