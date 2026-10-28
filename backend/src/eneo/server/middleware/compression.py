"""Gzip for text responses only, once, at level 6 (replaces Next's compress).

Starlette's GZipMiddleware would also compress downloads, Range responses and
every other type. This responder decides on ``http.response.start`` and passes
everything else through untouched, so downloads keep ``Content-Length``, SSE
stays unbuffered and 206 bodies stay byte-identical.
"""

from __future__ import annotations

from starlette.datastructures import Headers, MutableHeaders
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


def _accepts_gzip(accept_encoding: str) -> bool:
    """gzip (or *) is listed with a quality above zero (RFC 9110 §12.5.3)."""
    qualities: dict[str, float] = {}
    for item in accept_encoding.split(","):
        coding, *params = (part.strip() for part in item.split(";"))
        quality = 1.0
        for param in params:
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if coding:
            qualities[coding.lower()] = quality
    return qualities.get("gzip", qualities.get("*", 0.0)) > 0


class SelectiveGZipMiddleware(GZipMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app, minimum_size=500, compresslevel=6)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if _accepts_gzip(Headers(scope=scope).get("accept-encoding", "")):
            responder = _SelectiveGZipResponder(
                self.app, self.minimum_size, compresslevel=self.compresslevel
            )
            await responder(scope, receive, send)
            return

        async def send_with_vary(message: Message) -> None:
            # A response that could have been gzipped varies by Accept-Encoding,
            # so a cache does not hand this identity copy to a gzip client.
            if message["type"] == "http.response.start" and _compressible(
                message["status"], Headers(raw=message["headers"])
            ):
                MutableHeaders(scope=message).add_vary_header("Accept-Encoding")
            await send(message)

        await self.app(scope, receive, send_with_vary)
