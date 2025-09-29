"""Scrapy engine wrapper implementation."""

from pathlib import Path
from typing import AsyncIterator, TYPE_CHECKING

from intric.crawler.engines.base import CrawlerEngineAbstraction
from intric.crawler.parse_html import CrawledPage
from intric.websites.domain.crawl_run import CrawlType

if TYPE_CHECKING:
    pass


class ScrapyEngine(CrawlerEngineAbstraction):
    """Wrapper around the existing Scrapy implementation.

    This engine preserves all existing Scrapy functionality without modifications,
    maintaining backwards compatibility.
    """

    async def crawl(
        self,
        url: str,
        download_files: bool = False,
        crawl_type: CrawlType = CrawlType.CRAWL,
    ) -> AsyncIterator[CrawledPage]:
        """Execute crawl using Scrapy implementation.

        Note: Since circular imports were resolved by moving engine selection
        to the service layer, ScrapyEngine is now only used by crawl4ai code path.
        The Scrapy path continues to use the Crawler class directly.
        """
        # This engine is primarily for consistency with the abstraction
        # In practice, Scrapy crawls are handled directly by the service layer
        # using the existing Crawler class to avoid circular imports
        raise NotImplementedError(
            "ScrapyEngine is not directly used. Scrapy crawls are handled "
            "by the service layer using the existing Crawler class directly."
        )

    async def crawl_files(self, url: str) -> AsyncIterator[Path]:
        """Not directly used - see crawl() method."""
        raise NotImplementedError("See crawl() method documentation.")

    def validate_config(self) -> bool:
        """Validate Scrapy engine configuration."""
        return True