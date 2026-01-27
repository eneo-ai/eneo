import asyncio
import json
import logging
import os
import threading
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
from intric.main.exceptions import CrawlerException, CrawlTimeoutError
from intric.tenants.crawler_settings_helper import get_crawler_setting
from intric.websites.domain.crawl_run import CrawlType

logger = logging.getLogger(__name__)


class CrawlShutdownError(Exception):
    """Raised when crawler fails to shut down gracefully within timeout.

    This indicates the output file may be incomplete or corrupted because
    Scrapy was still writing when we tried to read it.
    """

    def __init__(self, url: str, shutdown_timeout: float):
        self.url = url
        self.shutdown_timeout = shutdown_timeout
        super().__init__(
            f"Crawler failed to shut down within {shutdown_timeout}s for {url} - "
            "output file may be incomplete"
        )


class CrawlManager:
    """Manages a single crawl operation with proper lifecycle control.

    This class solves the resource leak problem where Scrapy crawlers continue
    running in Twisted's reactor after timeout. By holding a reference to the
    crawler instance, we can explicitly stop it when needed.

    The key insight (from GPT-5.2 and Gemini-3-pro-preview consultation):
    - crochet's EventualResult.wait(timeout) only stops WAITING, not the crawler
    - Without explicit stop, the crawler keeps running in Twisted's reactor
    - We must call crawler.stop() INSIDE the reactor thread
    - We must wait for the crawl deferred to complete before reading results

    Usage:
        manager = CrawlManager()
        eventual_result = manager.start_crawl(...)
        try:
            eventual_result.wait(timeout=max_length)
        except TimeoutError:
            manager.stop_crawl()  # Gracefully stop the crawler
            if not manager.wait_for_completion():
                raise CrawlShutdownError(...)  # Don't read incomplete file!
    """

    def __init__(self):
        self._crawler = None
        self._crawl_deferred = None
        self._runner = None
        # Note: _stop_event removed - was unused (set but never waited on)
        self._completion_event = threading.Event()

    @crochet.run_in_reactor
    def start_crawl(
        self,
        spider_cls,
        *,
        filepath: str,
        files_dir: str | None = None,
        tenant_crawler_settings: dict[str, Any] | None = None,
        **spider_kwargs,
    ):
        """Start a crawl and return the EventualResult.

        Unlike the previous approach that lost the crawler reference,
        this method stores it so we can stop the crawler on timeout.

        Returns:
            EventualResult wrapping the crawl Deferred
        """
        self._runner = create_runner(
            filepath=filepath,
            files_dir=files_dir,
            tenant_crawler_settings=tenant_crawler_settings,
        )

        # Create crawler explicitly to keep reference for stop()
        self._crawler = self._runner.create_crawler(spider_cls)

        # Start crawl and store the deferred
        self._crawl_deferred = self._runner.crawl(self._crawler, **spider_kwargs)

        # Add callback to signal completion
        def on_complete(_):
            logger.debug("Crawl deferred completed")
            self._completion_event.set()

        def on_error(failure):
            logger.warning(f"Crawl deferred errored: {failure}")
            self._completion_event.set()

        self._crawl_deferred.addCallback(on_complete)
        self._crawl_deferred.addErrback(on_error)

        return self._crawl_deferred

    @crochet.run_in_reactor
    def stop_crawl(self, reason: str = "timeout"):
        """Stop the crawler gracefully from within Twisted's reactor.

        CRITICAL: This must run inside the reactor thread because:
        1. crawler.stop() interacts with Twisted internals
        2. It triggers cleanup that must happen in the reactor thread
        3. Calling from outside would cause thread-safety issues

        The @crochet.run_in_reactor decorator ensures this runs in the reactor.

        Args:
            reason: Why the crawl is being stopped (for logging)
        """
        if self._crawler is None:
            logger.warning("stop_crawl called but no crawler exists")
            return

        if self._crawler.crawling:
            logger.info(f"Stopping crawler: reason={reason}")
            # crawler.stop() is the proper Scrapy way to gracefully stop
            # It triggers spider_closed signal and allows cleanup
            self._crawler.stop()
        else:
            logger.debug("stop_crawl called but crawler was not crawling")

    def wait_for_completion(self, timeout: float = 10.0) -> bool:
        """Wait for the crawler to actually finish after stop() is called.

        After calling stop_crawl(), the crawler needs time to:
        1. Finish any in-flight requests
        2. Close the spider gracefully
        3. Flush any buffered writes to the JSONL file

        Args:
            timeout: Maximum seconds to wait for completion

        Returns:
            True if crawler completed within timeout, False otherwise
        """
        completed = self._completion_event.wait(timeout=timeout)
        if not completed:
            logger.warning(
                f"Crawler did not complete within {timeout}s after stop - "
                "partial results may be incomplete"
            )
        return completed


@dataclass
class Crawl:
    """Result of a web crawl operation.

    Attributes:
        pages: Iterator of crawled pages
        files: Optional iterator of downloaded files
        is_partial: True if crawl was terminated early (timeout, etc.)
        termination_reason: Why crawl ended ("completed", "timeout", "error")
        pages_count: Number of pages collected (for partial results reporting)
    """

    pages: Iterable[CrawledPage]
    files: Optional[Iterable[Path]]
    is_partial: bool = False
    termination_reason: str = "completed"
    pages_count: int = 0


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
        heartbeat_callback: Optional[Any] = None,
        heartbeat_interval: float = 60.0,
    ) -> None:
        """Async wrapper with tenant-aware timeout, graceful shutdown, and heartbeat.

        Uses CrawlManager to properly handle timeout scenarios:
        1. Start crawl with manager (keeps crawler reference)
        2. Run concurrent heartbeat task while crawl executes
        3. Wait for completion with timeout
        4. On timeout: stop crawler gracefully, wait for flush
        5. Verify shutdown succeeded before allowing file read

        Args:
            heartbeat_callback: Optional async callable to invoke periodically during crawl.
                              This keeps the job alive in monitoring systems.
            heartbeat_interval: Seconds between heartbeat calls (default 60s)

        This fixes the resource leak where crawlers continued running
        in Twisted's reactor after timeout.
        """
        manager = CrawlManager()
        timed_out = False
        shutdown_failed = False
        crawl_done = asyncio.Event()

        def blocking_crawl():
            nonlocal timed_out, shutdown_failed
            files_dir_str = str(files_dir) if files_dir and download_files else None

            eventual_result = manager.start_crawl(
                CrawlSpider,
                filepath=str(filepath),
                files_dir=files_dir_str,
                tenant_crawler_settings=tenant_crawler_settings,
                url=url,
                http_user=http_user,
                http_pass=http_pass,
            )

            try:
                # Block until crawl completes or timeout
                eventual_result.wait(timeout=max_length)
            except crochet.TimeoutError:
                timed_out = True
                logger.info(
                    f"Crawl timeout after {max_length}s for {url} - "
                    "stopping crawler gracefully"
                )
                # Stop the crawler gracefully inside reactor thread
                manager.stop_crawl(reason="timeout")
                # Wait for crawler to actually finish (flush writes)
                shutdown_ok = manager.wait_for_completion(timeout=10.0)
                if not shutdown_ok:
                    shutdown_failed = True
                    logger.error(
                        f"CRITICAL: Crawler failed to shut down within 10s for {url} - "
                        "output file may be incomplete"
                    )

        async def heartbeat_loop():
            """Run heartbeat while crawl executes in thread."""
            while not crawl_done.is_set():
                try:
                    if heartbeat_callback:
                        await heartbeat_callback()
                except Exception as e:
                    logger.warning(f"Heartbeat error during crawl: {e}")
                # Wait for interval or until crawl completes
                try:
                    await asyncio.wait_for(crawl_done.wait(), timeout=heartbeat_interval)
                    break  # Crawl completed
                except asyncio.TimeoutError:
                    pass  # Interval elapsed, continue heartbeat loop

        # Run crawl in thread with concurrent heartbeat
        if heartbeat_callback:
            heartbeat_task = asyncio.create_task(heartbeat_loop())
            try:
                await asyncio.to_thread(blocking_crawl)
            finally:
                crawl_done.set()
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
        else:
            await asyncio.to_thread(blocking_crawl)

        # Check shutdown status BEFORE allowing caller to read file
        if shutdown_failed:
            raise CrawlShutdownError(url=url, shutdown_timeout=10.0)

        if timed_out:
            raise CrawlTimeoutError(
                url=url,
                timeout_seconds=max_length,
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
        heartbeat_callback: Optional[Any] = None,
        heartbeat_interval: float = 60.0,
    ) -> None:
        """Async wrapper with tenant-aware timeout, graceful shutdown, and heartbeat for sitemap.

        Uses CrawlManager to properly handle timeout scenarios:
        1. Start crawl with manager (keeps crawler reference)
        2. Run concurrent heartbeat task while crawl executes
        3. Wait for completion with timeout
        4. On timeout: stop crawler gracefully, wait for flush
        5. Verify shutdown succeeded before allowing file read

        Args:
            heartbeat_callback: Optional async callable to invoke periodically during crawl.
            heartbeat_interval: Seconds between heartbeat calls (default 60s)
        """
        manager = CrawlManager()
        timed_out = False
        shutdown_failed = False
        crawl_done = asyncio.Event()

        def blocking_crawl():
            nonlocal timed_out, shutdown_failed

            eventual_result = manager.start_crawl(
                SitemapSpider,
                filepath=str(filepath),
                files_dir=None,  # Sitemap crawls don't download files
                tenant_crawler_settings=tenant_crawler_settings,
                sitemap_url=sitemap_url,
                http_user=http_user,
                http_pass=http_pass,
            )

            try:
                # Block until crawl completes or timeout
                eventual_result.wait(timeout=max_length)
            except crochet.TimeoutError:
                timed_out = True
                logger.info(
                    f"Sitemap crawl timeout after {max_length}s for {sitemap_url} - "
                    "stopping crawler gracefully"
                )
                # Stop the crawler gracefully inside reactor thread
                manager.stop_crawl(reason="timeout")
                # Wait for crawler to actually finish (flush writes)
                shutdown_ok = manager.wait_for_completion(timeout=10.0)
                if not shutdown_ok:
                    shutdown_failed = True
                    logger.error(
                        f"CRITICAL: Crawler failed to shut down within 10s for {sitemap_url} - "
                        "output file may be incomplete"
                    )

        async def heartbeat_loop():
            """Run heartbeat while crawl executes in thread."""
            while not crawl_done.is_set():
                try:
                    if heartbeat_callback:
                        await heartbeat_callback()
                except Exception as e:
                    logger.warning(f"Heartbeat error during sitemap crawl: {e}")
                try:
                    await asyncio.wait_for(crawl_done.wait(), timeout=heartbeat_interval)
                    break
                except asyncio.TimeoutError:
                    pass

        # Run crawl in thread with concurrent heartbeat
        if heartbeat_callback:
            heartbeat_task = asyncio.create_task(heartbeat_loop())
            try:
                await asyncio.to_thread(blocking_crawl)
            finally:
                crawl_done.set()
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
        else:
            await asyncio.to_thread(blocking_crawl)

        # Check shutdown status BEFORE allowing caller to read file
        if shutdown_failed:
            raise CrawlShutdownError(url=sitemap_url, shutdown_timeout=10.0)

        if timed_out:
            raise CrawlTimeoutError(
                url=sitemap_url,
                timeout_seconds=max_length,
            )

    @asynccontextmanager
    async def _crawl(
        self,
        func,
        *,
        max_length: int,
        heartbeat_callback: Optional[Any] = None,
        heartbeat_interval: float = 60.0,
        **kwargs,
    ):
        """Execute crawl function with timeout and yield results.

        Handles timeouts gracefully by salvaging partial results:
        - On successful completion: yields all pages with is_partial=False
        - On timeout WITH pages collected: yields partial pages with is_partial=True
        - On timeout with NO pages: raises CrawlTimeoutError
        - On other failures: raises CrawlerException

        Args:
            func: The async crawl function to execute
            max_length: Tenant-aware timeout in seconds
            heartbeat_callback: Optional async callable for heartbeat during crawl
            heartbeat_interval: Seconds between heartbeat calls (default: 60)
            **kwargs: Additional arguments for the crawl function
        """
        with NamedTemporaryFile(delete=False) as tmp_file:
            tmp_file_path = tmp_file.name
        tmp_dir_obj = TemporaryDirectory()
        tmp_dir = tmp_dir_obj.name

        is_partial = False
        termination_reason = "completed"
        url = kwargs.get("url") or kwargs.get("sitemap_url", "unknown")

        try:
            await func(
                filepath=tmp_file_path,
                files_dir=tmp_dir,
                max_length=max_length,
                heartbeat_callback=heartbeat_callback,
                heartbeat_interval=heartbeat_interval,
                **kwargs,
            )
        except CrawlTimeoutError as timeout_err:
            # Timeout occurred - check if we have partial results to salvage
            is_partial = True
            termination_reason = "timeout"

            # Note: CrawlManager.stop_crawl() + wait_for_completion() already
            # ensured the crawler finished and flushed writes before we get here.
            # The JSONL file is safe to read immediately.

            # Count pages in the spool file
            pages_count = 0
            try:
                file_size = os.stat(tmp_file_path).st_size
                if file_size > 0:
                    with open(tmp_file_path) as f:
                        pages_count = sum(1 for _ in f)
            except OSError:
                pages_count = 0

            if pages_count == 0:
                # No pages collected before timeout - this is a true failure
                # Clean up temp files before raising
                try:
                    os.unlink(tmp_file_path)
                    tmp_dir_obj.cleanup()
                except OSError:
                    pass
                raise CrawlTimeoutError(
                    url=url,
                    timeout_seconds=timeout_err.timeout_seconds,
                    pages_collected=0,
                    message=f"Crawl timeout: exceeded {timeout_err.timeout_seconds}s for {url} with no pages collected",
                )

            # Update the timeout error with page count for logging
            timeout_err.pages_collected = pages_count

        try:
            # Check if file exists and has content
            file_size = os.stat(tmp_file_path).st_size
            if file_size == 0:
                raise CrawlerException(f"Crawl failed for {url}: no pages returned")

            # Count pages for the result
            with open(tmp_file_path) as f:
                pages_count = sum(1 for _ in f)

            def _iter_pages():
                with open(tmp_file_path) as f:
                    for line in f:
                        jsonl = json.loads(line)
                        yield CrawledPage(**jsonl)

            def _iter_files():
                p = Path(tmp_dir)
                return p.iterdir()

            yield Crawl(
                pages=_iter_pages(),
                files=_iter_files(),
                is_partial=is_partial,
                termination_reason=termination_reason,
                pages_count=pages_count,
            )

        finally:
            # Clean up temp files
            try:
                os.unlink(tmp_file_path)
            except OSError:
                pass
            try:
                tmp_dir_obj.cleanup()
            except OSError:
                pass

    @asynccontextmanager
    async def crawl(
        self,
        url: str,
        download_files: bool = False,
        crawl_type: CrawlType = CrawlType.CRAWL,
        http_user: str = None,
        http_pass: str = None,
        tenant_crawler_settings: dict[str, Any] | None = None,
        heartbeat_callback: Optional[Any] = None,
        heartbeat_interval: float = 60.0,
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
            heartbeat_callback: Optional async callable for heartbeat during crawl.
                Called at heartbeat_interval during crawl to maintain liveness.
                Used to refresh Redis TTLs and DB timestamps during long crawls.
            heartbeat_interval: Seconds between heartbeat calls (default: 60)

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
                heartbeat_callback=heartbeat_callback,
                heartbeat_interval=heartbeat_interval,
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
                heartbeat_callback=heartbeat_callback,
                heartbeat_interval=heartbeat_interval,
                sitemap_url=url,
                http_user=http_user,
                http_pass=http_pass,
                tenant_crawler_settings=tenant_crawler_settings,
            ) as crawl_result:
                yield crawl_result

        else:
            raise ValueError(f"crawl_type {crawl_type} is not a CrawlType")
