"""Abstract base class for crawler engine implementations."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import AsyncIterator

from intric.crawler.parse_html import CrawledPage
from intric.websites.domain.crawl_run import CrawlType


class CrawlerEngineAbstraction(ABC):
    """Abstract interface for crawler engine implementations."""

    @abstractmethod
    async def crawl(
        self,
        url: str,
        download_files: bool = False,
        crawl_type: CrawlType = CrawlType.CRAWL,
    ) -> AsyncIterator[CrawledPage]:
        """Execute crawl and yield CrawledPage objects.

        Args:
            url: The URL to crawl
            download_files: Whether to download files during crawling
            crawl_type: The type of crawl to perform (CRAWL or SITEMAP)

        Yields:
            CrawledPage objects containing crawled data
        """
        pass

    @abstractmethod
    async def crawl_files(self, url: str) -> AsyncIterator[Path]:
        """Execute crawl and yield downloaded file paths.

        Args:
            url: The URL to crawl for files

        Yields:
            Path objects to downloaded files
        """
        pass

    @abstractmethod
    def validate_config(self) -> bool:
        """Validate engine-specific configuration.

        Returns:
            True if configuration is valid, False otherwise
        """
        pass