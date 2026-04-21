from typing import Literal, Sequence

class AsyncTavilyClient:
    def __init__(
        self,
        api_key: str | None = None,
        company_info_tags: Sequence[str] = ("news", "general", "finance"),
        proxies: dict[str, str] | None = None,
    ) -> None: ...

    async def search(
        self,
        query: str,
        search_depth: Literal["basic", "advanced"] = "basic",
        topic: Literal["general", "news", "finance"] = "general",
        time_range: Literal["day", "week", "month", "year"] | None = None,
        days: int = 7,
        max_results: int = 5,
        include_domains: Sequence[str] | None = None,
        exclude_domains: Sequence[str] | None = None,
        include_answer: bool | Literal["basic", "advanced"] = False,
        include_raw_content: bool = False,
        include_images: bool = False,
        timeout: int = 60,
        **kwargs: object,
    ) -> dict[str, object]: ...
