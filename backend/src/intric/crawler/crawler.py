import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any, Iterable, Optional

import crochet
from scrapy.crawler import CrawlerRunner

from intric.crawler.parse_html import CrawledPage
from intric.crawler.pipelines import FileNamePipeline
from intric.crawler.spiders.crawl_spider import CrawlSpider
from intric.crawler.spiders.sitemap_spider import SitemapSpider
from intric.main.exceptions import CrawlerException
from intric.tenants.crawler_settings_helper import get_crawler_setting
from intric.websites.domain.crawl_run import CrawlType


@dataclass
class Crawl:
    pages: Iterable[CrawledPage]
    files: Optional[Iterable[Path]]


def create_runner(
    filepath: str,
    files_dir: Optional[str] = None,
    tenant_crawler_settings: dict[str, Any] | None = None,
):
    """Create a Scrapy CrawlerRunner with tenant-aware settings.

    Settings are resolved in priority order:
    1. Tenant-specific override (from DB via API)
    2. Environment variable default
    3. Hardcoded default

    Args:
        filepath: Path to output JSONL file for crawled pages
        files_dir: Optional directory for downloaded files
        tenant_crawler_settings: Optional tenant-specific settings from DB
    """
    settings = {
        "FEEDS": {filepath: {"format": "jsonl", "item_classes": [CrawledPage]}},
        # All settings use get_crawler_setting() for tenant-aware resolution
        "CLOSESPIDER_ITEMCOUNT": get_crawler_setting(
            "closespider_itemcount", tenant_crawler_settings
        ),
        "AUTOTHROTTLE_ENABLED": get_crawler_setting(
            "autothrottle_enabled", tenant_crawler_settings
        ),
        "ROBOTSTXT_OBEY": get_crawler_setting("obey_robots", tenant_crawler_settings),
        "DOWNLOAD_MAXSIZE": get_crawler_setting(
            "download_max_size", tenant_crawler_settings
        ),
        # Timeout settings to fail faster on unreachable sites
        # Why: Default 180s timeout × 3 retries = ~13 min waste per unreachable site
        # These are per-REQUEST timeouts, NOT total crawl time (crawl_max_length handles that)
        "DOWNLOAD_TIMEOUT": get_crawler_setting(
            "download_timeout", tenant_crawler_settings
        ),
        "DNS_TIMEOUT": get_crawler_setting("dns_timeout", tenant_crawler_settings),
        "RETRY_TIMES": get_crawler_setting("retry_times", tenant_crawler_settings),
        "RETRY_ENABLED": True,
    }

    if files_dir is not None:
        settings["ITEM_PIPELINES"] = {FileNamePipeline: 300}
        settings["FILES_STORE"] = files_dir

    return CrawlerRunner(settings=settings)


class Crawler:
    """Web crawler with tenant-aware timeout support.

    The crawler uses crochet.run_in_reactor() + EventualResult.wait() for
    dynamic timeout control, allowing each tenant to have their own
    crawl_max_length setting while properly integrating with Twisted's reactor.
    """

    @crochet.run_in_reactor
    @staticmethod
    def _run_crawl_deferred(
        url: str,
        download_files: bool = False,
        *,
        filepath: Path,
        files_dir: Optional[Path],
        http_user: str = None,
        http_pass: str = None,
        tenant_crawler_settings: dict[str, Any] | None = None,
    ):
        """Run crawl in Twisted reactor, returns EventualResult.

        The @crochet.run_in_reactor() decorator schedules this function
        to run in Twisted's reactor thread and returns an EventualResult
        that wraps the Deferred from runner.crawl().
        """
        files_dir = files_dir if download_files else None
        runner = create_runner(
            filepath=filepath,
            files_dir=files_dir,
            tenant_crawler_settings=tenant_crawler_settings,
        )
        return runner.crawl(CrawlSpider, url=url, http_user=http_user, http_pass=http_pass)

    @crochet.run_in_reactor
    @staticmethod
    def _run_sitemap_crawl_deferred(
        sitemap_url: str,
        *,
        filepath: Path,
        files_dir: Optional[Path],
        http_user: str = None,
        http_pass: str = None,
        tenant_crawler_settings: dict[str, Any] | None = None,
    ):
        """Run sitemap crawl in Twisted reactor, returns EventualResult.

        The @crochet.run_in_reactor() decorator schedules this function
        to run in Twisted's reactor thread and returns an EventualResult
        that wraps the Deferred from runner.crawl().
        """
        runner = create_runner(
            filepath=filepath,
            tenant_crawler_settings=tenant_crawler_settings,
        )
        return runner.crawl(
            SitemapSpider, sitemap_url=sitemap_url, http_user=http_user, http_pass=http_pass
        )

    @staticmethod
    async def _run_crawl_with_timeout(
        url: str,
        download_files: bool = False,
        *,
        filepath: Path,
        files_dir: Optional[Path],
        http_user: str = None,
        http_pass: str = None,
        tenant_crawler_settings: dict[str, Any] | None = None,
        max_length: int,
    ) -> None:
        """Async wrapper with tenant-aware timeout for regular crawl.

        Uses crochet's EventualResult.wait(timeout) to block until crawl
        completes or timeout is reached. The timeout is evaluated at runtime,
        allowing per-tenant configuration.
        """

        def blocking_crawl():
            eventual_result = Crawler._run_crawl_deferred(
                url,
                download_files,
                filepath=filepath,
                files_dir=files_dir,
                http_user=http_user,
                http_pass=http_pass,
                tenant_crawler_settings=tenant_crawler_settings,
            )
            # Block until crawl completes or timeout - runtime timeout value!
            eventual_result.wait(timeout=max_length)

        try:
            await asyncio.to_thread(blocking_crawl)
        except crochet.TimeoutError:
            raise CrawlerException(
                f"Crawl timeout: exceeded {max_length} seconds for {url}"
            )

    @staticmethod
    async def _run_sitemap_crawl_with_timeout(
        sitemap_url: str,
        *,
        filepath: Path,
        files_dir: Optional[Path],
        http_user: str = None,
        http_pass: str = None,
        tenant_crawler_settings: dict[str, Any] | None = None,
        max_length: int,
    ) -> None:
        """Async wrapper with tenant-aware timeout for sitemap crawl.

        Uses crochet's EventualResult.wait(timeout) to block until crawl
        completes or timeout is reached. The timeout is evaluated at runtime,
        allowing per-tenant configuration.
        """

        def blocking_crawl():
            eventual_result = Crawler._run_sitemap_crawl_deferred(
                sitemap_url,
                filepath=filepath,
                files_dir=files_dir,
                http_user=http_user,
                http_pass=http_pass,
                tenant_crawler_settings=tenant_crawler_settings,
            )
            # Block until crawl completes or timeout - runtime timeout value!
            eventual_result.wait(timeout=max_length)

        try:
            await asyncio.to_thread(blocking_crawl)
        except crochet.TimeoutError:
            raise CrawlerException(
                f"Crawl timeout: exceeded {max_length} seconds for {sitemap_url}"
            )

    @asynccontextmanager
    async def _crawl(self, func, *, max_length: int, **kwargs):
        """Execute crawl function with timeout and yield results.

        Args:
            func: The async crawl function to execute
            max_length: Tenant-aware timeout in seconds
            **kwargs: Additional arguments for the crawl function
        """
        with NamedTemporaryFile() as tmp_file:
            with TemporaryDirectory() as tmp_dir:
                await func(
                    filepath=tmp_file.name,
                    files_dir=tmp_dir,
                    max_length=max_length,
                    **kwargs,
                )

                # If the result file is empty
                # (This will fail if the expected result is no pages but some files)
                if os.stat(tmp_file.name).st_size == 0:
                    # Extract URL for better error context in logs
                    url = kwargs.get("url") or kwargs.get("sitemap_url", "unknown")
                    raise CrawlerException(f"Crawl failed for {url}: no pages returned")

                def _iter_pages():
                    with open(tmp_file.name) as f:
                        for line in f:
                            jsonl = json.loads(line)
                            yield CrawledPage(**jsonl)

                def _iter_files():
                    p = Path(tmp_dir)
                    return p.iterdir()

                yield Crawl(pages=_iter_pages(), files=_iter_files())

    @asynccontextmanager
    async def crawl(
        self,
        url: str,
        download_files: bool = False,
        crawl_type: CrawlType = CrawlType.CRAWL,
        http_user: str = None,
        http_pass: str = None,
        tenant_crawler_settings: dict[str, Any] | None = None,
    ):
        """Execute a web crawl with tenant-aware settings.

        Args:
            url: URL to crawl (or sitemap URL for SITEMAP crawl type)
            download_files: Whether to download linked files
            crawl_type: Type of crawl (CRAWL or SITEMAP)
            http_user: HTTP basic auth username (optional)
            http_pass: HTTP basic auth password (optional)
            tenant_crawler_settings: Tenant-specific settings from DB (optional)
                If provided, these override environment variable defaults.

        Note:
            crawl_max_length is now tenant-aware. The timeout is resolved at runtime
            from tenant settings (if provided) or falls back to environment default.
        """
        # Get tenant-aware max crawl length (resolved at runtime, not import time)
        max_length = get_crawler_setting("crawl_max_length", tenant_crawler_settings)

        if crawl_type == CrawlType.CRAWL:
            async with self._crawl(
                self._run_crawl_with_timeout,
                max_length=max_length,
                url=url,
                download_files=download_files,
                http_user=http_user,
                http_pass=http_pass,
                tenant_crawler_settings=tenant_crawler_settings,
            ) as crawl_result:
                yield crawl_result

        elif crawl_type == CrawlType.SITEMAP:
            async with self._crawl(
                self._run_sitemap_crawl_with_timeout,
                max_length=max_length,
                sitemap_url=url,
                http_user=http_user,
                http_pass=http_pass,
                tenant_crawler_settings=tenant_crawler_settings,
            ) as crawl_result:
                yield crawl_result

        else:
            raise ValueError(f"crawl_type {crawl_type} is not a CrawlType")
