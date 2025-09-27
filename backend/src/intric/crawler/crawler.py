import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Iterable, Optional

import crochet
from scrapy.crawler import CrawlerRunner

from intric.crawler.parse_html import CrawledPage
from intric.crawler.pipelines import FileNamePipeline
from intric.crawler.spiders.crawl_spider import CrawlSpider
from intric.crawler.spiders.sitemap_spider import SitemapSpider
from intric.main.config import SETTINGS
from intric.main.exceptions import CrawlerException
from intric.main.logging import get_logger
from intric.websites.domain.crawl_run import CrawlType


@dataclass
class Crawl:
    pages: Iterable[CrawledPage]
    files: Optional[Iterable[Path]]


def create_runner(filepath: str, files_dir: Optional[str] = None):
    settings = {
        "FEEDS": {filepath: {"format": "jsonl", "item_classes": [CrawledPage]}},
        "CLOSESPIDER_ITEMCOUNT": SETTINGS.closespider_itemcount,
        "AUTOTHROTTLE_ENABLED": SETTINGS.autothrottle_enabled,
        "ROBOTSTXT_OBEY": SETTINGS.obey_robots,
        "DOWNLOAD_MAXSIZE": SETTINGS.upload_max_file_size,
    }

    if files_dir is not None:
        settings["ITEM_PIPELINES"] = {FileNamePipeline: 300}
        settings["FILES_STORE"] = files_dir

    return CrawlerRunner(settings=settings)


class Crawler:
    @crochet.wait_for(SETTINGS.crawl_max_length)
    @staticmethod
    def _run_crawl(
        url: str,
        download_files: bool = False,
        *,
        filepath: Path,
        files_dir: Optional[Path],
        http_user: str = None,
        http_pass: str = None,
    ):
        files_dir = files_dir if download_files else None
        runner = create_runner(filepath=filepath, files_dir=files_dir)
        return runner.crawl(CrawlSpider, url=url, http_user=http_user, http_pass=http_pass)

    @crochet.wait_for(SETTINGS.crawl_max_length)
    @staticmethod
    def _run_sitemap_crawl(
        sitemap_url: str, 
        *, 
        filepath: Path, 
        files_dir: Optional[Path],
        http_user: str = None, 
        http_pass: str = None, 
    ):
        runner = create_runner(filepath=filepath)
        return runner.crawl(SitemapSpider, sitemap_url=sitemap_url, http_user=http_user, http_pass=http_pass)

    @asynccontextmanager
    async def _crawl(self, func, **kwargs):
        """
        Internal method to execute crawling with proper error handling and cleanup.

        Args:
            func: The crawling function to execute (_run_crawl or _run_sitemap_crawl)
            **kwargs: Additional arguments passed to the crawling function

        Yields:
            Crawl: Object containing iterators for pages and files

        Raises:
            CrawlerException: If crawling fails or produces no results
        """
        with NamedTemporaryFile() as tmp_file:
            with TemporaryDirectory() as tmp_dir:
                try:
                    # Execute the crawl function in a separate thread
                    await asyncio.to_thread(func, filepath=tmp_file.name, files_dir=tmp_dir, **kwargs)
                except Exception as e:
                    raise CrawlerException(f"Crawler execution failed: {str(e)}") from e

                # Validate that crawl produced results
                if os.stat(tmp_file.name).st_size == 0:
                    raise CrawlerException(
                        "Crawl failed - no pages were successfully crawled. "
                        "This could indicate network issues, invalid URL, robots.txt restrictions, "
                        "or authentication problems."
                    )

                def _iter_pages():
                    """Iterator for crawled pages with error handling."""
                    try:
                        with open(tmp_file.name) as f:
                            for line_num, line in enumerate(f, 1):
                                try:
                                    jsonl = json.loads(line)
                                    yield CrawledPage(**jsonl)
                                except (json.JSONDecodeError, TypeError, ValueError) as e:
                                    # Log but don't fail the entire crawl for individual page parsing errors
                                    logger = get_logger(__name__)
                                    logger.warning(f"Failed to parse page data at line {line_num}: {str(e)}")
                                    continue
                    except IOError as e:
                        logger = get_logger(__name__)
                        logger.error(f"Failed to read crawl results file: {str(e)}")
                        # Return empty iterator if file reading fails
                        return
                        yield  # Make this a generator

                def _iter_files():
                    """Iterator for downloaded files with error handling."""
                    try:
                        p = Path(tmp_dir)
                        return p.iterdir()
                    except OSError as e:
                        logger = get_logger(__name__)
                        logger.warning(f"Failed to iterate files directory: {str(e)}")
                        return iter([])  # Return empty iterator

                yield Crawl(pages=_iter_pages(), files=_iter_files())

    @asynccontextmanager
    async def crawl(
        self,
        url: str,
        download_files: bool = False,
        crawl_type: CrawlType = CrawlType.CRAWL,
        http_user: str = None,
        http_pass: str = None,
    ):
        """
        Main crawl method that coordinates different types of crawls.

        Args:
            url: The URL to crawl (website URL for CRAWL, sitemap URL for SITEMAP)
            download_files: Whether to download and process files (only for CRAWL type)
            crawl_type: Type of crawl to perform (CRAWL or SITEMAP)
            http_user: Username for HTTP basic authentication (optional)
            http_pass: Password for HTTP basic authentication (optional)

        Yields:
            Crawl: Object containing iterators for pages and files

        Raises:
            ValueError: If crawl_type is not supported
            CrawlerException: If crawling fails
        """
        logger = get_logger(__name__)
        logger.info(f"Starting {crawl_type.value} crawl for URL: {url}")

        # Log authentication status (without exposing credentials)
        auth_status = "with authentication" if http_user else "without authentication"
        logger.debug(f"Crawl configuration: files={download_files}, auth={auth_status}")

        try:
            if crawl_type == CrawlType.CRAWL:
                async with self._crawl(
                    self._run_crawl,
                    url=url,
                    download_files=download_files,
                    http_user=http_user,
                    http_pass=http_pass,
                ) as crawl_result:
                    logger.info(f"Standard crawl completed successfully for {url}")
                    yield crawl_result

            elif crawl_type == CrawlType.SITEMAP:
                # Sitemap crawls don't support file downloads
                if download_files:
                    logger.warning("File downloads not supported for sitemap crawls, ignoring download_files=True")

                async with self._crawl(
                    self._run_sitemap_crawl,
                    sitemap_url=url,
                    http_user=http_user,
                    http_pass=http_pass,
                ) as crawl_result:
                    logger.info(f"Sitemap crawl completed successfully for {url}")
                    yield crawl_result

            else:
                error_msg = f"Unsupported crawl_type: {crawl_type}. Must be CRAWL or SITEMAP."
                logger.error(error_msg)
                raise ValueError(error_msg)

        except Exception as e:
            logger.error(f"Crawl failed for {url} (type: {crawl_type}): {str(e)}")
            raise
