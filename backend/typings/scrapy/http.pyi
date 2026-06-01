from typing import Any

class Headers:
    def get(self, key: bytes, default: Any = None) -> bytes | None: ...


class Response:
    url: str
    body: bytes
    text: str
    headers: Headers

    def css(self, query: str) -> SelectorList: ...


class TextResponse(Response): ...


class SelectorList:
    def get(self) -> str | None: ...

