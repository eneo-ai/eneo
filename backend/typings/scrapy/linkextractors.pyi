from typing import Sequence

class LinkExtractor:
    def __init__(
        self,
        allow: str | Sequence[str] | None = None,
        deny_extensions: Sequence[str] | None = None,
    ) -> None: ...

