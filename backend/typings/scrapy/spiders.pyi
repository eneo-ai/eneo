from typing import Any

from .http import Response
from .linkextractors import LinkExtractor

class Spider:
    name: str


class CrawlSpider(Spider):
    allowed_domains: list[str]
    start_urls: list[str]
    rules: list[Rule]

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    def parse_start_url(self, response: Response) -> Any: ...


class SitemapSpider(Spider):
    sitemap_urls: list[str]

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    def parse(self, response: Response) -> Any: ...


class Rule:
    def __init__(
        self,
        link_extractor: LinkExtractor,
        callback: Any = None,
        follow: bool = False,
    ) -> None: ...

