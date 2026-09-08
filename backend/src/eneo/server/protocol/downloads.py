import unicodedata
from collections.abc import AsyncIterable, Awaitable, Callable, Mapping
from urllib.parse import quote

from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send


class ClosingStreamingResponse(StreamingResponse):
    """Close the backing read even when ASGI abandons the body iterator."""

    def __init__(
        self,
        content: AsyncIterable[bytes],
        *,
        close: Callable[[], Awaitable[None]],
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
    ) -> None:
        super().__init__(
            content,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
        )
        self._close = close
        self._closed = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._close()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.aclose()


def content_disposition_header(disposition: str, filename: str) -> str:
    """Serialize a safe Content-Disposition value for a downloaded resource."""
    safe_ascii = bool(filename) and all(
        0x20 <= ord(character) <= 0x7E and character not in {'"', "\\"}
        for character in filename
    )
    if safe_ascii:
        return f'{disposition}; filename="{filename}"'

    ascii_name = (
        unicodedata.normalize("NFKD", filename)
        .encode("ascii", errors="ignore")
        .decode("ascii")
    )
    fallback = (
        "".join(
            character
            if 0x20 <= ord(character) <= 0x7E and character not in {'"', "\\"}
            else "_"
            for character in ascii_name
        )
        or "download"
    )
    encoded = quote(filename, safe="", encoding="utf-8", errors="strict")
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
