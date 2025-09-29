"""Crawler engine abstraction layer."""

from .base import CrawlerEngineAbstraction
from .scrapy_engine import ScrapyEngine
from .crawl4ai_engine import Crawl4aiEngine
from intric.websites.domain.crawler_engine import CrawlerEngine


def get_engine(crawler_engine: CrawlerEngine) -> CrawlerEngineAbstraction:
    """Factory function to get the appropriate crawler engine implementation.

    Args:
        crawler_engine: The engine type to instantiate

    Returns:
        Concrete implementation of CrawlerEngineAbstraction

    Raises:
        ValueError: If the engine type is not supported
    """
    if crawler_engine == CrawlerEngine.SCRAPY:
        return ScrapyEngine()
    elif crawler_engine == CrawlerEngine.CRAWL4AI:
        return Crawl4aiEngine()
    else:
        raise ValueError(f"Unsupported crawler engine: {crawler_engine}")


__all__ = [
    "CrawlerEngineAbstraction",
    "ScrapyEngine",
    "Crawl4aiEngine",
    "get_engine",
]