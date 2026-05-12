import asyncio
import json
import logging
import os
import threading
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import (
    Any,
    Callable,
    Coroutine,
    Iterable,
    Optional,
    Protocol,
    Self,
    cast,
    runtime_checkable,
)

import crochet
from scrapy.crawler import Crawler as ScrapyCrawler
from scrapy.crawler import CrawlerRunner
from scrapy.spiders import Spider
from twisted.python.failure import Failure

from intric.crawler.parse_html import CrawledPage
from intric.crawler.pipelines import (
    FILE_STATUS_TOO_LARGE,
    FileNamePipeline,
    FileSizeLimitStatsExtension,
)
from intric.crawler.spiders.crawl_spider import CrawlSpider
from intric.crawler.spiders.sitemap_spider import SitemapSpider, SourceRetainedUrl
from intric.main.config import get_settings
from intric.main.exceptions import CrawlTimeoutError
from intric.tenants.crawler_settings_helper import (
    TenantCrawlerSettings,
    get_crawler_setting,
)
from intric.websites.domain.crawl_outcome import CrawlTerminationReason
from intric.websites.domain.crawl_run import CrawlType

logger = logging.getLogger(__name__)


class _StatsCollector(Protocol):
    def get_stats(self) -> Mapping[object, object]: ...


class _CrawlerWithStats(Protocol):
    stats: _StatsCollector


@runtime_checkable
class _DiagnosticsOwner(Protocol):
    @property
    def diagnostics(self) -> "CrawlDiagnostics": ...


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
    """Owns one Scrapy crawl lifecycle.

    A timeout from crochet's `EventualResult.wait()` stops waiting, not the
    underlying Scrapy crawl. Keep the crawler and Deferred references here so
    timeout handling can stop the crawler inside Twisted's reactor and wait for
    feed writes to flush before reading output files.
    """

    def __init__(self) -> None:
        super().__init__()
        self._crawler: ScrapyCrawler | None = None
        # Scrapy's runner.crawl() returns Deferred; Scrapy has no py.typed so
        # the Deferred type parameter is Unknown at the boundary.
        self._crawl_deferred: Any = None  # Deferred from Scrapy/Twisted
        self._runner: CrawlerRunner | None = None
        self._completion_event = threading.Event()
        self._stats_snapshot: dict[str, object] = {}

    @crochet.run_in_reactor
    def start_crawl(
        self,
        spider_cls: type[Spider] | str | ScrapyCrawler,
        *,
        filepath: str | Path,
        files_dir: str | Path | None = None,
        http_cache_dir: str | Path | None = None,
        source_retained_filepath: str | Path | None = None,
        tenant_crawler_settings: TenantCrawlerSettings | None = None,
        **spider_kwargs: Any,
    ) -> Any:
        """Start a crawl and return the EventualResult.

        The active crawler reference is retained so timeout handling can stop
        the crawl and wait for feed exporters to flush before reading output.

        Returns:
            EventualResult wrapping the crawl Deferred
        """
        self._runner = create_runner(
            filepath=filepath,
            files_dir=files_dir,
            http_cache_dir=http_cache_dir,
            source_retained_filepath=source_retained_filepath,
            tenant_crawler_settings=tenant_crawler_settings,
        )

        # Create crawler explicitly to keep reference for stop()
        self._crawler = self._runner.create_crawler(spider_cls)

        # Start crawl and store the deferred.
        self._crawl_deferred = self._runner.crawl(  # pyright: ignore[reportUnknownMemberType]  # Scrapy has no py.typed stubs
            self._crawler, **spider_kwargs
        )

        def on_complete(_: Any) -> None:
            self._capture_stats_snapshot()
            logger.debug("Crawl deferred completed")
            self._completion_event.set()

        def on_error(failure: Failure) -> None:
            self._capture_stats_snapshot()
            logger.warning(f"Crawl deferred errored: {failure}")
            self._completion_event.set()

        self._crawl_deferred.addCallback(on_complete)
        self._crawl_deferred.addErrback(on_error)

        return self._crawl_deferred

    def _capture_stats_snapshot(self) -> None:
        if self._crawler is None:
            self._stats_snapshot = {}
            return

        try:
            crawler_with_stats = cast(_CrawlerWithStats, self._crawler)
            stats = crawler_with_stats.stats.get_stats()
        except Exception as exc:
            logger.warning(
                "Failed to capture Scrapy crawl stats",
                extra={"error": str(exc)},
            )
            self._stats_snapshot = {}
            return

        self._stats_snapshot = {str(key): value for key, value in stats.items()}

    @property
    def diagnostics(self) -> "CrawlDiagnostics":
        return CrawlDiagnostics.from_scrapy_stats(self._stats_snapshot)

    @crochet.run_in_reactor
    def stop_crawl(self, reason: str = "timeout") -> None:
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


def _empty_int_counts() -> dict[int, int]:
    return {}


def _empty_string_counts() -> dict[str, int]:
    return {}


@dataclass(frozen=True)
class CrawlDiagnostics:
    request_count: int = 0
    response_count: int = 0
    item_scraped_count: int = 0
    file_count: int = 0
    robotstxt_forbidden_count: int = 0
    httperror_ignored_count: int = 0
    response_status_counts: dict[int, int] = field(default_factory=_empty_int_counts)
    robotstxt_status_counts: dict[int, int] = field(default_factory=_empty_int_counts)
    downloader_exception_counts: dict[str, int] = field(
        default_factory=_empty_string_counts
    )
    file_status_counts: dict[str, int] = field(default_factory=_empty_string_counts)
    finish_reason: str | None = None
    elapsed_time_seconds: float | None = None

    @classmethod
    def from_scrapy_stats(cls, stats: Mapping[object, object] | object) -> Self:
        if not isinstance(stats, Mapping):
            return cls()
        stats_mapping = cast(Mapping[object, object], stats)
        typed_stats: dict[object, object] = dict(stats_mapping.items())

        return cls(
            request_count=_int_stat(typed_stats, "downloader/request_count"),
            response_count=_int_stat(typed_stats, "downloader/response_count"),
            item_scraped_count=_int_stat(typed_stats, "item_scraped_count"),
            file_count=_int_stat(typed_stats, "file_count"),
            robotstxt_forbidden_count=_int_stat(typed_stats, "robotstxt/forbidden"),
            httperror_ignored_count=_int_stat(
                typed_stats, "httperror/response_ignored_count"
            ),
            response_status_counts=_status_counts(
                typed_stats, "downloader/response_status_count/"
            ),
            robotstxt_status_counts=_status_counts(
                typed_stats, "robotstxt/response_status_count/"
            ),
            downloader_exception_counts=_string_counts(
                typed_stats, "downloader/exception_type_count/"
            ),
            file_status_counts=_string_counts(typed_stats, "file_status_count/"),
            finish_reason=_str_stat(typed_stats, "finish_reason"),
            elapsed_time_seconds=_float_stat(typed_stats, "elapsed_time_seconds"),
        )

    @property
    def files_too_large_skipped_count(self) -> int:
        return self.file_status_counts.get(FILE_STATUS_TOO_LARGE, 0)

    def describe_empty_output(self) -> str:
        if self.request_count == 0:
            return "Scrapy did not issue any requests; check crawler startup and runner setup"

        if self.robotstxt_forbidden_count > 0:
            detail = f"robots.txt blocked {self.robotstxt_forbidden_count} request(s)"
            if self.robotstxt_status_counts:
                detail += f"; robots responses: {_format_int_counts(self.robotstxt_status_counts)}"
            return detail

        if self.downloader_exception_counts:
            return (
                "downloader exceptions: "
                f"{_format_string_counts(self.downloader_exception_counts)}"
            )

        if self.files_too_large_skipped_count > 0:
            return (
                f"{self.files_too_large_skipped_count} file(s) exceeded the crawler "
                "download size limit"
            )

        if self.item_scraped_count > 0:
            return (
                f"Scrapy scraped {self.item_scraped_count} item(s), but no page items "
                "reached the page feed; check FEEDS item_classes and item pipelines"
            )

        if self.response_status_counts:
            detail = (
                "responses received but no page items scraped; HTTP statuses: "
                f"{_format_int_counts(self.response_status_counts)}"
            )
            if self.httperror_ignored_count > 0:
                detail += f"; httperror ignored={self.httperror_ignored_count}"
            if self.finish_reason:
                detail += f"; finish_reason={self.finish_reason}"
            return detail

        detail = f"requests={self.request_count}, responses={self.response_count}"
        if self.finish_reason:
            detail += f", finish_reason={self.finish_reason}"
        return detail

    def to_log_fields(self) -> dict[str, object]:
        return {
            "request_count": self.request_count,
            "response_count": self.response_count,
            "item_scraped_count": self.item_scraped_count,
            "file_count": self.file_count,
            "robotstxt_forbidden_count": self.robotstxt_forbidden_count,
            "httperror_ignored_count": self.httperror_ignored_count,
            "response_status_counts": {
                str(status): count
                for status, count in sorted(self.response_status_counts.items())
            },
            "robotstxt_status_counts": {
                str(status): count
                for status, count in sorted(self.robotstxt_status_counts.items())
            },
            "downloader_exception_counts": self.downloader_exception_counts,
            "file_status_counts": self.file_status_counts,
            "finish_reason": self.finish_reason,
            "elapsed_time_seconds": self.elapsed_time_seconds,
        }


def _int_stat(stats: dict[object, object], key: str) -> int:
    value = stats.get(key)
    return value if isinstance(value, int) else 0


def _float_stat(stats: dict[object, object], key: str) -> float | None:
    value = stats.get(key)
    if isinstance(value, int | float):
        return float(value)
    return None


def _str_stat(stats: dict[object, object], key: str) -> str | None:
    value = stats.get(key)
    return value if isinstance(value, str) else None


def _status_counts(stats: dict[object, object], prefix: str) -> dict[int, int]:
    counts: dict[int, int] = {}
    for key, value in stats.items():
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        if not isinstance(value, int):
            continue
        status_text = key.removeprefix(prefix)
        if not status_text.isdigit():
            continue
        counts[int(status_text)] = value
    return dict(sorted(counts.items()))


def _string_counts(stats: dict[object, object], prefix: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, value in stats.items():
        if isinstance(key, str) and key.startswith(prefix) and isinstance(value, int):
            counts[key.removeprefix(prefix)] = value
    return dict(sorted(counts.items()))


def _format_int_counts(counts: dict[int, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


def _format_string_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


@dataclass(frozen=True)
class Crawl:
    """Result of a web crawl operation.

    Attributes:
        pages: Iterator of crawled pages
        files: Optional iterator of downloaded files
        is_partial: True if crawl was terminated early (timeout, etc.)
        termination_reason: Why crawl ended ("completed", "timeout")
        pages_count: Number of pages collected (for partial results reporting)
        source_retained_urls: Sitemap URLs present in source but not fetched
    """

    pages: Iterable[CrawledPage]
    files: Optional[Iterable[Path]]
    is_partial: bool = False
    termination_reason: CrawlTerminationReason = "completed"
    pages_count: int = 0
    source_retained_urls: frozenset[str] = frozenset()
    diagnostics: CrawlDiagnostics = field(default_factory=CrawlDiagnostics)

    @property
    def source_retained_count(self) -> int:
        return len(self.source_retained_urls)


@dataclass(frozen=True, slots=True)
class _CrawlOutputSummary:
    pages_count: int
    source_retained_urls: frozenset[str]

    @property
    def has_output(self) -> bool:
        return self.pages_count > 0 or bool(self.source_retained_urls)


def create_runner(
    filepath: str | Path,
    files_dir: Optional[str | Path] = None,
    http_cache_dir: Optional[str | Path] = None,
    source_retained_filepath: Optional[str | Path] = None,
    http_cache_expiration_seconds: int | None = None,
    tenant_crawler_settings: TenantCrawlerSettings | None = None,
) -> CrawlerRunner:
    """Create a Scrapy CrawlerRunner with tenant-aware settings.

    Args:
        filepath: Path to output JSONL file for crawled pages
        files_dir: Optional directory for downloaded files
        tenant_crawler_settings: Tenant-specific crawler settings snapshot
    """
    filepath_str = str(filepath)
    feeds: dict[str, dict[str, object]] = {
        filepath_str: {"format": "jsonl", "item_classes": [CrawledPage]}
    }
    if source_retained_filepath is not None:
        feeds[str(source_retained_filepath)] = {
            "format": "jsonl",
            "item_classes": [SourceRetainedUrl],
        }

    settings_obj = get_settings()
    # Scrapy settings values have heterogeneous types; dict[str, Any] is correct here.
    settings: dict[str, Any] = {
        "FEEDS": feeds,
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
        "EXTENSIONS": {FileSizeLimitStatsExtension: 500},
    }

    if http_cache_dir is not None:
        settings.update(
            {
                "HTTPCACHE_ENABLED": True,
                "HTTPCACHE_DIR": str(http_cache_dir),
                "HTTPCACHE_POLICY": "scrapy.extensions.httpcache.RFC2616Policy",
                "HTTPCACHE_STORAGE": "scrapy.extensions.httpcache.FilesystemCacheStorage",
                "HTTPCACHE_EXPIRATION_SECS": (
                    http_cache_expiration_seconds
                    if http_cache_expiration_seconds is not None
                    else settings_obj.crawl_http_cache_expiration_seconds
                ),
            }
        )

    if files_dir is not None:
        settings["ITEM_PIPELINES"] = {FileNamePipeline: 300}
        settings["FILES_STORE"] = str(files_dir)

    return CrawlerRunner(settings=settings)


def _read_source_retained_urls(filepath: str | Path) -> frozenset[str]:
    path = Path(filepath)
    if not path.exists() or path.stat().st_size == 0:
        return frozenset()

    retained_urls: list[str] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            try:
                payload: object = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(
                    "Ignoring malformed source-retained crawler line",
                    extra={"path": str(path)},
                )
                continue

            url = (
                cast(dict[str, object], payload).get("url")
                if isinstance(payload, dict)
                else None
            )
            if isinstance(url, str) and url:
                retained_urls.append(url)

    return frozenset(retained_urls)


def _count_jsonl_lines(filepath: str | Path) -> int:
    try:
        if os.stat(filepath).st_size == 0:
            return 0
        with open(filepath) as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _read_crawl_outputs(
    *,
    pages_filepath: str | Path,
    source_retained_filepath: str | Path,
) -> _CrawlOutputSummary:
    return _CrawlOutputSummary(
        pages_count=_count_jsonl_lines(pages_filepath),
        source_retained_urls=_read_source_retained_urls(source_retained_filepath),
    )


def _crawl_manager_diagnostics(manager: object) -> CrawlDiagnostics:
    if isinstance(manager, _DiagnosticsOwner):
        return manager.diagnostics
    return CrawlDiagnostics()


# Type alias for the async crawl functions used by _crawl()
_CrawlFunc = Callable[..., Coroutine[Any, Any, CrawlDiagnostics]]


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
        filepath: str | Path,
        files_dir: Optional[str | Path],
        http_cache_dir: Optional[str | Path] = None,
        http_user: str | None = None,
        http_pass: str | None = None,
        tenant_crawler_settings: TenantCrawlerSettings | None = None,
    ) -> Any:
        """Run crawl in Twisted reactor, returns EventualResult.

        The @crochet.run_in_reactor() decorator schedules this function
        to run in Twisted's reactor thread and returns an EventualResult
        that wraps the Deferred from runner.crawl().

        Returns Any because Scrapy has no py.typed stubs; the actual runtime
        value is Deferred[None] but pyright cannot verify the type parameter.
        """
        files_dir = files_dir if download_files else None
        runner = create_runner(
            filepath=filepath,
            files_dir=files_dir,
            http_cache_dir=http_cache_dir,
            tenant_crawler_settings=tenant_crawler_settings,
        )
        return runner.crawl(  # pyright: ignore[reportUnknownMemberType]  # Scrapy has no py.typed stubs
            CrawlSpider, url=url, http_user=http_user, http_pass=http_pass
        )

    @crochet.run_in_reactor
    @staticmethod
    def _run_sitemap_crawl_deferred(
        sitemap_url: str,
        *,
        filepath: str | Path,
        files_dir: Optional[str | Path],
        http_cache_dir: Optional[str | Path] = None,
        http_user: str | None = None,
        http_pass: str | None = None,
        source_retained_filepath: str | Path | None = None,
        lastmod_skip_cutoff: datetime | None = None,
        lastmod_skip_allowed_urls: Iterable[str] | None = None,
        tenant_crawler_settings: TenantCrawlerSettings | None = None,
    ) -> Any:
        """Run sitemap crawl in Twisted reactor, returns EventualResult.

        The @crochet.run_in_reactor() decorator schedules this function
        to run in Twisted's reactor thread and returns an EventualResult
        that wraps the Deferred from runner.crawl().

        Returns Any because Scrapy has no py.typed stubs; the actual runtime
        value is Deferred[None] but pyright cannot verify the type parameter.
        """
        runner = create_runner(
            filepath=filepath,
            http_cache_dir=http_cache_dir,
            source_retained_filepath=source_retained_filepath,
            tenant_crawler_settings=tenant_crawler_settings,
        )
        return runner.crawl(  # pyright: ignore[reportUnknownMemberType]
            SitemapSpider,
            sitemap_url=sitemap_url,
            http_user=http_user,
            http_pass=http_pass,
            lastmod_skip_cutoff=lastmod_skip_cutoff,
            lastmod_skip_allowed_urls=lastmod_skip_allowed_urls,
        )

    @staticmethod
    async def _run_crawl_with_timeout(
        url: str,
        download_files: bool = False,
        *,
        filepath: str | Path,
        files_dir: Optional[str | Path],
        http_cache_dir: Optional[str | Path] = None,
        http_user: str | None = None,
        http_pass: str | None = None,
        tenant_crawler_settings: TenantCrawlerSettings | None = None,
        max_length: int,
        heartbeat_callback: Optional[Callable[[], Coroutine[Any, Any, None]]] = None,
        heartbeat_interval: float = 60.0,
    ) -> CrawlDiagnostics:
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

        def blocking_crawl() -> None:
            nonlocal timed_out, shutdown_failed
            files_dir_str = str(files_dir) if files_dir and download_files else None

            eventual_result = manager.start_crawl(
                CrawlSpider,
                filepath=str(filepath),
                files_dir=files_dir_str,
                http_cache_dir=http_cache_dir,
                tenant_crawler_settings=tenant_crawler_settings,
                url=url,
                http_user=http_user,
                http_pass=http_pass,
            )

            try:
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

        async def heartbeat_loop() -> None:
            """Run heartbeat while crawl executes in thread."""
            while not crawl_done.is_set():
                try:
                    if heartbeat_callback:
                        await heartbeat_callback()
                except Exception as e:
                    logger.warning(f"Heartbeat error during crawl: {e}")
                try:
                    await asyncio.wait_for(
                        crawl_done.wait(), timeout=heartbeat_interval
                    )
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
                diagnostics=_crawl_manager_diagnostics(manager),
            )

        return _crawl_manager_diagnostics(manager)

    @staticmethod
    async def _run_sitemap_crawl_with_timeout(
        sitemap_url: str,
        *,
        filepath: str | Path,
        files_dir: Optional[str | Path],
        http_cache_dir: Optional[str | Path] = None,
        http_user: str | None = None,
        http_pass: str | None = None,
        source_retained_filepath: str | Path | None = None,
        lastmod_skip_cutoff: datetime | None = None,
        lastmod_skip_allowed_urls: Iterable[str] | None = None,
        tenant_crawler_settings: TenantCrawlerSettings | None = None,
        max_length: int,
        heartbeat_callback: Optional[Callable[[], Coroutine[Any, Any, None]]] = None,
        heartbeat_interval: float = 60.0,
    ) -> CrawlDiagnostics:
        """Async wrapper with tenant-aware timeout, graceful shutdown, and heartbeat for sitemap.

        Uses CrawlManager to properly handle timeout scenarios:
        1. Start crawl with manager (keeps crawler reference)
        2. Run concurrent heartbeat task while crawl executes
        3. Wait for completion with timeout
        4. On timeout: stop crawler gracefully, wait for flush
        5. Verify shutdown succeeded before allowing file read

        Args:
            heartbeat_callback: Optional async callable for heartbeat during crawl.
            heartbeat_interval: Seconds between heartbeat calls (default 60s)
        """
        manager = CrawlManager()
        timed_out = False
        shutdown_failed = False
        crawl_done = asyncio.Event()

        def blocking_crawl() -> None:
            nonlocal timed_out, shutdown_failed

            eventual_result = manager.start_crawl(
                SitemapSpider,
                filepath=str(filepath),
                files_dir=None,  # Sitemap crawls don't download files
                http_cache_dir=http_cache_dir,
                source_retained_filepath=source_retained_filepath,
                tenant_crawler_settings=tenant_crawler_settings,
                sitemap_url=sitemap_url,
                http_user=http_user,
                http_pass=http_pass,
                lastmod_skip_cutoff=lastmod_skip_cutoff,
                lastmod_skip_allowed_urls=lastmod_skip_allowed_urls,
            )

            try:
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

        async def heartbeat_loop() -> None:
            """Run heartbeat while crawl executes in thread."""
            while not crawl_done.is_set():
                try:
                    if heartbeat_callback:
                        await heartbeat_callback()
                except Exception as e:
                    logger.warning(f"Heartbeat error during sitemap crawl: {e}")
                try:
                    await asyncio.wait_for(
                        crawl_done.wait(), timeout=heartbeat_interval
                    )
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
                diagnostics=_crawl_manager_diagnostics(manager),
            )

        return _crawl_manager_diagnostics(manager)

    @asynccontextmanager
    async def _crawl(
        self,
        func: _CrawlFunc,
        *,
        max_length: int,
        heartbeat_callback: Optional[Callable[[], Coroutine[Any, Any, None]]] = None,
        heartbeat_interval: float = 60.0,
        **kwargs: Any,
    ):
        """Execute crawl function with timeout and yield results.

        Handles timeouts gracefully by salvaging partial results:
        - On successful completion: yields all pages with is_partial=False
        - On timeout WITH output collected: yields partial output with is_partial=True
        - On timeout with no output: yields an empty typed timeout result
        - On successful completion with no output: yields an empty typed result

        Args:
            func: The async crawl function to execute
            max_length: Tenant-aware timeout in seconds
            heartbeat_callback: Optional async callable for heartbeat during crawl
            heartbeat_interval: Seconds between heartbeat calls (default: 60)
            **kwargs: Additional arguments for the crawl function
        """
        with NamedTemporaryFile(delete=False) as tmp_file:
            tmp_file_path = tmp_file.name
        with NamedTemporaryFile(delete=False) as source_retained_file:
            source_retained_file_path = source_retained_file.name
        tmp_dir_obj = TemporaryDirectory()
        tmp_dir = tmp_dir_obj.name

        is_partial = False
        termination_reason: CrawlTerminationReason = "completed"
        crawl_outputs: _CrawlOutputSummary | None = None
        crawl_diagnostics = CrawlDiagnostics()

        try:
            crawl_kwargs = dict(kwargs)
            if "sitemap_url" in crawl_kwargs:
                crawl_kwargs["source_retained_filepath"] = source_retained_file_path

            crawl_diagnostics = await func(
                filepath=tmp_file_path,
                files_dir=tmp_dir,
                max_length=max_length,
                heartbeat_callback=heartbeat_callback,
                heartbeat_interval=heartbeat_interval,
                **crawl_kwargs,
            )
        except CrawlTimeoutError as timeout_err:
            # Timeout occurred - check if we have partial results to salvage
            is_partial = True
            termination_reason = "timeout"

            # Note: CrawlManager.stop_crawl() + wait_for_completion() already
            # ensured the crawler finished and flushed writes before we get here.
            # The JSONL files are safe to read immediately.

            crawl_outputs = _read_crawl_outputs(
                pages_filepath=tmp_file_path,
                source_retained_filepath=source_retained_file_path,
            )

            timeout_err.pages_collected = crawl_outputs.pages_count
            if timeout_err.diagnostics is not None:
                crawl_diagnostics = timeout_err.diagnostics

        try:
            if crawl_outputs is None:
                crawl_outputs = _read_crawl_outputs(
                    pages_filepath=tmp_file_path,
                    source_retained_filepath=source_retained_file_path,
                )

            def _iter_pages() -> Iterable[CrawledPage]:
                with open(tmp_file_path) as f:
                    for line in f:
                        jsonl = json.loads(line)
                        yield CrawledPage(**jsonl)

            def _iter_files() -> Iterable[Path]:
                p = Path(tmp_dir)
                return p.iterdir()

            yield Crawl(
                pages=_iter_pages(),
                files=_iter_files(),
                is_partial=is_partial,
                termination_reason=termination_reason,
                pages_count=crawl_outputs.pages_count,
                source_retained_urls=crawl_outputs.source_retained_urls,
                diagnostics=crawl_diagnostics,
            )

        finally:
            # Clean up temp files
            try:
                os.unlink(tmp_file_path)
            except OSError:
                pass
            try:
                os.unlink(source_retained_file_path)
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
        http_user: str | None = None,
        http_pass: str | None = None,
        tenant_crawler_settings: TenantCrawlerSettings | None = None,
        http_cache_dir: Optional[str | Path] = None,
        sitemap_lastmod_skip_cutoff: datetime | None = None,
        sitemap_lastmod_skip_allowed_urls: Iterable[str] | None = None,
        heartbeat_callback: Optional[Callable[[], Coroutine[Any, Any, None]]] = None,
        heartbeat_interval: float = 60.0,
    ):
        """Execute a web crawl with tenant-aware settings.

        Args:
            url: URL to crawl (or sitemap URL for SITEMAP crawl type)
            download_files: Whether to download linked files
            crawl_type: Type of crawl (CRAWL or SITEMAP)
            http_user: HTTP basic auth username (optional)
            http_pass: HTTP basic auth password (optional)
            tenant_crawler_settings: Tenant-specific crawler settings snapshot.
            heartbeat_callback: Optional async callable for heartbeat during crawl.
                Called at heartbeat_interval during crawl to maintain liveness.
                Used to refresh Redis TTLs and DB timestamps during long crawls.
            heartbeat_interval: Seconds between heartbeat calls (default: 60)

        Note:
            crawl_max_length is now tenant-aware. The timeout is resolved at runtime
            from tenant settings (if provided) or falls back to environment default.
        """
        # Get tenant-aware max crawl length (resolved at runtime, not import time).
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
                http_cache_dir=http_cache_dir,
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
                http_cache_dir=http_cache_dir,
                lastmod_skip_cutoff=sitemap_lastmod_skip_cutoff,
                lastmod_skip_allowed_urls=sitemap_lastmod_skip_allowed_urls,
            ) as crawl_result:
                yield crawl_result

        else:
            raise ValueError(f"crawl_type {crawl_type} is not a CrawlType")
