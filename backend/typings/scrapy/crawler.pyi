from typing import Any

from .spiders import Spider

class Crawler:
    crawling: bool

    def stop(self) -> None: ...


class CrawlerRunner:
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    def create_crawler(self, spider_cls: type[Spider] | str | Crawler) -> Crawler: ...

    def crawl(self, crawler: Any, **spider_kwargs: Any) -> Any: ...
