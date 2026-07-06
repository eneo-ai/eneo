"""Crawl execution delegated to the external crawler service.

Eneo owns crawl administration (websites, schedules, run history, circuit
breaker, slots) but never executes crawls in-process: the crawl is POSTed to
the crawler service, which streams results back as NDJSON events:

    {"type": "page", "page": {"url": ..., "title": ..., "raw_text": ..., "etag": ..., "last_modified": ..., "file_links": [...]}}
    {"type": "unchanged", "url": ...}
    {"type": "failed", "url": ..., "status": ..., "error_message": ...}
    {"type": "done", "status": "completed" | "cancelled" | "failed", "outcome": {...}}

Pages are spooled to a temp JSONL file during streaming and iterated only
after the stream ends; the worker consumes the resulting ``Crawl`` (file-backed
page iterator, temp dir of files, partial-result salvage) exactly as it always
has. Linked files are downloaded by this client, never by the service, so the
service stays binary-free and the worker's hash-skip/extract loop applies.
"""

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any, Callable, Coroutine, Iterable, Optional, cast
from urllib.parse import unquote, urlparse

import aiohttp
from typing_extensions import TypedDict

from eneo.crawler.models import Crawl, CrawledPage
from eneo.crawler.url_scope import host_of, same_host
from eneo.main.exceptions import CrawlerException, CrawlTimeoutError
from eneo.tenants.crawler_settings_helper import get_crawler_setting
from eneo.websites.domain.crawl_run import CrawlType

logger = logging.getLogger(__name__)


class ConditionalGetHint(TypedDict):
    """Per-URL cache validators from a prior crawl. The service turns these
    into If-None-Match / If-Modified-Since headers and answers 304s with an
    ``unchanged`` event instead of re-downloading the body."""

    url: str
    etag: Optional[str]
    last_modified: Optional[str]


# Wire-contract cap on conditional_gets entries per crawl request
_MAX_CONDITIONAL_GETS = 50_000

# Margin on top of the service-side max_seconds before the client gives up
# on the stream; the service is expected to terminate the crawl itself.
_CLIENT_TIMEOUT_MARGIN_SECONDS = 120

# Connect timeout for opening the stream; the stream itself has no total
# timeout (a crawl legitimately runs for hours).
_CONNECT_TIMEOUT_SECONDS = 30

# Total timeout for the /v1/preview dry-run used to validate sitemap configs;
# it runs inline in API requests, so it must stay bounded.
_PREVIEW_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class SitemapValidation:
    """Outcome of asking the crawler service whether a sitemap crawl of a
    seed URL could yield pages.

    ``valid`` is False only on definitive evidence: the seed is reachable and
    the service's sitemap discovery found nothing. An unreachable seed or a
    failed preview passes, so a flaky probe never blocks configuration — the
    crawl-time zero-pages error remains the backstop.
    """

    valid: bool
    reason: Optional[str] = None


_FILENAME_SANITIZE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_BYTES = 200


def _filename_for_link(link_url: str, taken: set[str], index: int) -> str:
    """Stable, sanitized filename for a downloaded link.

    Human-readable basename, length-capped, deduplicated. The worker uses the
    name as the blob title for hash-skip comparisons, so it must be
    deterministic per URL basename.
    """
    basename = unquote(Path(urlparse(link_url).path).name) or f"file-{index}"
    basename = _FILENAME_SANITIZE.sub("_", basename)
    while len(basename.encode("utf-8")) > _MAX_FILENAME_BYTES:
        basename = basename[1:]
    name = basename
    suffix = 1
    while name in taken:
        name = f"{suffix}_{basename}"
        suffix += 1
    taken.add(name)
    return name


class RemoteCrawler:
    """HTTP client for the external crawler service (stream delivery)."""

    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        headers = {"accept": "application/x-ndjson"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _preview(
        self,
        url: str,
        *,
        http_user: Optional[str],
        http_pass: Optional[str],
    ) -> dict[str, Any] | None:
        """POST /v1/preview and return the parsed body, or None when the
        preview could not be obtained (non-200, network error, bad JSON).

        Sitemap crawls treat ``url`` as a site seed: the service discovers the
        sitemap itself, via robots.txt ``Sitemap:`` directives first and de-facto
        locations (/sitemap.xml and friends) second, and reports that discovery
        in the response without running a real crawl.
        """
        request_body: dict[str, Any] = {
            "url": url,
            "crawl_type": "sitemap",
            # The preview runs a capped sample crawl alongside the sitemap
            # probe; only the sitemap discovery is consumed here
            "max_sample_fetches": 1,
            "http_auth": (
                {"user": http_user, "password": http_pass}
                if http_user and http_pass
                else None
            ),
        }
        headers = {"accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/v1/preview",
                    json=request_body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=_PREVIEW_TIMEOUT_SECONDS),
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            "Sitemap preview returned non-200",
                            extra={"url": url, "status": response.status},
                        )
                        return None
                    return cast("dict[str, Any]", await response.json())
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            logger.warning(
                "Sitemap preview unavailable",
                extra={"url": url, "error": str(exc)},
            )
            return None

    async def validate_sitemap_source(
        self,
        url: str,
        *,
        http_user: Optional[str] = None,
        http_pass: Optional[str] = None,
    ) -> SitemapValidation:
        """Ask the service whether a sitemap crawl of ``url`` could yield pages.

        The /v1/preview dry-run reports the service's sitemap discovery without
        running a crawl. An unavailable preview is fail-open: the configuration
        is allowed rather than blocked on a transient service hiccup.
        """
        data = await self._preview(url, http_user=http_user, http_pass=http_pass)
        if data is None:
            return SitemapValidation(valid=True)

        sitemap: dict[str, Any] = data.get("sitemap") or {}
        seed: dict[str, Any] = data.get("seed") or {}
        if sitemap.get("found"):
            # The service scopes sitemap entries to the seed URL's path: a
            # seed pointing at the sitemap document itself (the pre-service
            # convention) scope-filters out every page and yields nothing
            if sitemap.get("url_count") == 0:
                return SitemapValidation(
                    valid=False,
                    reason=(
                        "a sitemap was found, but none of its URLs fall "
                        "within the configured URL's path scope. Sitemap "
                        "crawls treat the URL as the site (or section) to "
                        "ingest, so use the site root (e.g. "
                        "https://example.com) instead of the sitemap "
                        "document itself"
                    ),
                )
            return SitemapValidation(valid=True)
        if not seed.get("reachable"):
            # Host down right now; transient unreachability must not lock
            # the operator out of a real sitemap
            return SitemapValidation(valid=True)
        return SitemapValidation(
            valid=False,
            reason=(
                "no sitemap was found for the site (robots.txt declares "
                "none and none exists at the common locations). Use the "
                '"crawl" type instead'
            ),
        )

    async def discover_sitemap_locations(
        self,
        url: str,
        *,
        http_user: Optional[str] = None,
        http_pass: Optional[str] = None,
    ) -> list[str]:
        """The top-level sitemap document URLs the service discovers for the
        site seed ``url`` (robots.txt ``Sitemap:`` directives and verified
        default locations), via /v1/preview.

        These are the URLs the scheduled-skip fingerprint must be computed
        over: a sitemap crawl is configured with the site seed, not the sitemap
        document, so Eneo cannot otherwise know which document to fingerprint.
        Returns an empty list when none are found or the preview is unavailable,
        which keeps the caller on a full crawl.
        """
        data = await self._preview(url, http_user=http_user, http_pass=http_pass)
        sitemap: dict[str, Any] = (data or {}).get("sitemap") or {}
        if not sitemap.get("found"):
            return []
        locations: list[Any] = sitemap.get("locations") or []
        return [loc for loc in locations if isinstance(loc, str) and loc]

    async def _stream_crawl(
        self,
        session: aiohttp.ClientSession,
        *,
        url: str,
        crawl_type: CrawlType,
        download_files: bool,
        http_user: str | None,
        http_pass: str | None,
        tenant_crawler_settings: dict[str, Any] | None,
        max_length: int,
        spool_path: str,
        conditional_gets: list[ConditionalGetHint] | None,
        unchanged_urls: list[str],
    ) -> tuple[int, int, list[str], dict[str, Any] | None, str | None]:
        """Consume the NDJSON stream into the spool file.

        Returns (pages_count, failed_count, file_links, outcome, done_status).

        ``unchanged_urls`` is a caller-owned accumulator (not a return value)
        so URLs already confirmed unchanged survive a mid-stream timeout or
        disconnect, the same way spooled pages do.
        """
        request_body: dict[str, Any] = {
            "url": url,
            "crawl_type": crawl_type.value,
            # Whole-site parity with Eneo's crawl semantics: the service
            # defaults to depth 1; 10 is its maximum
            "depth": 10,
            "http_auth": (
                {"user": http_user, "password": http_pass}
                if http_user and http_pass
                else None
            ),
            "index_linked_files": download_files,
            "limits": {
                "max_pages": get_crawler_setting(
                    "closespider_itemcount", tenant_crawler_settings
                ),
                "max_seconds": max_length,
            },
            "delivery": {"mode": "stream"},
        }
        if conditional_gets:
            if len(conditional_gets) > _MAX_CONDITIONAL_GETS:
                logger.warning(
                    "Truncating conditional_gets to wire-contract cap",
                    extra={
                        "url": url,
                        "hints": len(conditional_gets),
                        "cap": _MAX_CONDITIONAL_GETS,
                    },
                )
                conditional_gets = conditional_gets[:_MAX_CONDITIONAL_GETS]
            request_body["conditional_gets"] = conditional_gets

        pages_count = 0
        failed_count = 0
        file_links: list[str] = []
        seen_links: set[str] = set()
        outcome: dict[str, Any] | None = None
        done_status: str | None = None
        done_error: str | None = None
        event_counts: dict[str, int] = {}

        async with session.post(
            f"{self.base_url}/v1/crawls",
            json=request_body,
            headers=self._headers(),
            timeout=aiohttp.ClientTimeout(
                total=None, connect=_CONNECT_TIMEOUT_SECONDS, sock_read=None
            ),
        ) as response:
            if response.status != 200:
                body = (await response.text())[:500]
                raise CrawlerException(
                    f"Crawler service returned {response.status} for {url}: {body}"
                )

            with open(spool_path, "w", encoding="utf-8") as spool:
                async for raw_line in response.content:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Skipping malformed crawler service event",
                            extra={
                                "url": url,
                                "line_prefix": line[:100].decode(errors="replace"),
                            },
                        )
                        continue

                    event_type = event.get("type")
                    event_counts[str(event_type)] = (
                        event_counts.get(str(event_type), 0) + 1
                    )
                    if event_type == "page":
                        page_obj = cast("dict[str, Any]", event.get("page") or {})
                        page_url = page_obj.get("url")
                        content = (
                            page_obj.get("raw_text") or page_obj.get("content") or ""
                        )
                        if not page_url:
                            continue
                        spool.write(
                            json.dumps(
                                {
                                    "url": page_url,
                                    "title": page_obj.get("title") or page_url,
                                    "content": content,
                                    "etag": page_obj.get("etag"),
                                    "last_modified": page_obj.get("last_modified"),
                                }
                            )
                            + "\n"
                        )
                        pages_count += 1
                        if download_files:
                            raw_links: list[object] = page_obj.get("file_links") or []
                            for link in raw_links:
                                if isinstance(link, dict):
                                    link_url = cast("dict[str, object]", link).get(
                                        "url"
                                    )
                                else:
                                    link_url = link
                                if (
                                    isinstance(link_url, str)
                                    and link_url
                                    and link_url not in seen_links
                                ):
                                    seen_links.add(link_url)
                                    file_links.append(link_url)
                    elif event_type == "unchanged":
                        unchanged_url = event.get("url")
                        if unchanged_url:
                            unchanged_urls.append(unchanged_url)
                    elif event_type == "failed":
                        failed_count += 1
                    elif event_type == "done":
                        outcome = event.get("outcome") or {}
                        done_status = event.get("status")
                        done_error = event.get("error")
                    # Other event types (robots, skipped_*, ...) are tolerated
                    # and ignored: the worker has no use for them today.

        logger.info(
            "Crawler service stream consumed: url=%s events=%s status=%s outcome=%s",
            url,
            event_counts or "none",
            done_status,
            outcome,
        )
        if done_status == "failed":
            # Service-side crawl failure; pages already streamed stay valid
            logger.warning(
                "Crawler service reported failure for %s: %s", url, done_error
            )
        return pages_count, failed_count, file_links, outcome, done_status

    async def _download_files(
        self,
        session: aiohttp.ClientSession,
        file_links: list[str],
        files_dir: str,
        *,
        crawl_host: str | None,
        http_user: str | None,
        http_pass: str | None,
        tenant_crawler_settings: dict[str, Any] | None,
    ) -> None:
        """Fetch linked files into the temp dir (best effort, per-file).

        The crawler service never transfers binaries; the worker fetches them
        directly so the existing hash-skip + TextExtractor loop applies.

        ``file_links`` come from the service and may name any host. Credentials
        are domain-locked, so only links on ``crawl_host`` (the seed host the
        Basic Auth was registered for) are fetched, and only those carry auth;
        off-host or non-http(s) links are skipped rather than fetched with the
        site's credentials.
        """
        max_size = get_crawler_setting("download_max_size", tenant_crawler_settings)
        timeout_seconds = get_crawler_setting(
            "download_timeout", tenant_crawler_settings
        )
        auth_header = (
            aiohttp.encode_basic_auth(http_user, http_pass)
            if http_user and http_pass
            else None
        )
        taken: set[str] = set()

        for index, link_url in enumerate(file_links):
            if not same_host(link_url, crawl_host):
                # Domain-locked credentials must not follow a link off the
                # crawl host; skip rather than fetch (and never with auth)
                logger.warning(
                    "Skipping linked file outside crawl host",
                    extra={"file_url": link_url, "crawl_host": crawl_host},
                )
                continue
            target = Path(files_dir) / _filename_for_link(link_url, taken, index)
            try:
                async with session.get(
                    link_url,
                    headers=(
                        {"Authorization": auth_header}
                        if auth_header is not None
                        else None
                    ),
                    timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            "Skipping linked file (non-200)",
                            extra={"file_url": link_url, "status": response.status},
                        )
                        continue
                    declared = response.content_length
                    if declared is not None and declared > max_size:
                        logger.warning(
                            "Skipping linked file (exceeds download_max_size)",
                            extra={"file_url": link_url, "size": declared},
                        )
                        continue
                    written = 0
                    with open(target, "wb") as out:
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            written += len(chunk)
                            if written > max_size:
                                raise CrawlerException("download_max_size exceeded")
                            out.write(chunk)
            except (aiohttp.ClientError, asyncio.TimeoutError, CrawlerException) as exc:
                logger.warning(
                    "Failed to download linked file, skipping",
                    extra={"file_url": link_url, "error": str(exc)},
                )
                target.unlink(missing_ok=True)

    @asynccontextmanager
    async def crawl(
        self,
        url: str,
        download_files: bool = False,
        crawl_type: CrawlType = CrawlType.CRAWL,
        http_user: str | None = None,
        http_pass: str | None = None,
        tenant_crawler_settings: dict[str, Any] | None = None,
        heartbeat_callback: Optional[Callable[[], Coroutine[Any, Any, None]]] = None,
        heartbeat_interval: float = 60.0,
        conditional_gets: list[ConditionalGetHint] | None = None,
    ):
        """Same contract as Crawler.crawl: yields a Crawl with file-backed
        iterators after the (remote) crawl finished, salvaging partial results
        on timeout or stream interruption.

        ``conditional_gets`` carries per-URL cache validators from the prior
        crawl; URLs the server answers 304 for come back on
        ``Crawl.unchanged_urls`` instead of as pages."""
        max_length = get_crawler_setting("crawl_max_length", tenant_crawler_settings)

        with NamedTemporaryFile(delete=False) as tmp_file:
            spool_path = tmp_file.name
        tmp_dir_obj = TemporaryDirectory()

        is_partial = False
        termination_reason = "completed"
        pages_count = 0
        failed_count = 0
        file_links: list[str] = []
        outcome: dict[str, Any] | None = None
        unchanged_urls: list[str] = []

        stream_done = asyncio.Event()

        async def heartbeat_loop() -> None:
            while not stream_done.is_set():
                try:
                    if heartbeat_callback:
                        await heartbeat_callback()
                except Exception as e:
                    logger.warning(f"Heartbeat error during remote crawl: {e}")
                try:
                    await asyncio.wait_for(
                        stream_done.wait(), timeout=heartbeat_interval
                    )
                    break
                except asyncio.TimeoutError:
                    pass

        def _cleanup() -> None:
            try:
                os.unlink(spool_path)
            except OSError:
                pass
            try:
                tmp_dir_obj.cleanup()
            except OSError:
                pass

        try:
            async with aiohttp.ClientSession() as session:
                heartbeat_task = (
                    asyncio.create_task(heartbeat_loop())
                    if heartbeat_callback
                    else None
                )
                try:
                    async with asyncio.timeout(
                        max_length + _CLIENT_TIMEOUT_MARGIN_SECONDS
                    ):
                        (
                            pages_count,
                            failed_count,
                            file_links,
                            outcome,
                            done_status,
                        ) = await self._stream_crawl(
                            session,
                            url=url,
                            crawl_type=crawl_type,
                            download_files=download_files,
                            http_user=http_user,
                            http_pass=http_pass,
                            tenant_crawler_settings=tenant_crawler_settings,
                            max_length=max_length,
                            spool_path=spool_path,
                            conditional_gets=conditional_gets,
                            unchanged_urls=unchanged_urls,
                        )
                    if done_status == "cancelled":
                        # The service aborted the crawl itself (its
                        # max_seconds wall clock); pages received so far are
                        # valid, same salvage semantics as a local timeout
                        is_partial = True
                        termination_reason = "timeout"
                    elif done_status == "failed":
                        is_partial = True
                        termination_reason = "error"
                    logger.info(
                        "Remote crawl stream finished",
                        extra={
                            "url": url,
                            "pages": pages_count,
                            "failed": failed_count,
                            "termination_reason": termination_reason,
                        },
                    )
                except TimeoutError:
                    # Client-side ceiling: service did not finish within
                    # max_seconds + margin. Salvage whatever reached the
                    # spool (and any 304-confirmed URLs), like any other
                    # early termination.
                    pages_count = self._count_spool_lines(spool_path)
                    if pages_count == 0 and not unchanged_urls:
                        _cleanup()
                        raise CrawlTimeoutError(
                            url=url,
                            timeout_seconds=max_length,
                            pages_collected=0,
                            message=(
                                f"Remote crawl timeout: exceeded {max_length}s for "
                                f"{url} with no pages collected"
                            ),
                        )
                    is_partial = True
                    termination_reason = "timeout"
                except aiohttp.ClientError as exc:
                    pages_count = self._count_spool_lines(spool_path)
                    if pages_count == 0 and not unchanged_urls:
                        _cleanup()
                        raise CrawlerException(
                            f"Crawler service stream failed for {url}: {exc}"
                        )
                    # Stream broke mid-crawl with results on disk: salvage,
                    # same as a timeout
                    is_partial = True
                    termination_reason = "stream_interrupted"
                    logger.warning(
                        "Crawler service stream interrupted, salvaging partial results",
                        extra={"url": url, "pages": pages_count, "error": str(exc)},
                    )
                finally:
                    stream_done.set()
                    if heartbeat_task is not None:
                        heartbeat_task.cancel()
                        try:
                            await heartbeat_task
                        except asyncio.CancelledError:
                            pass

                # An entirely-304 crawl is a legitimate success: zero pages
                # streamed because nothing changed since the last crawl
                if pages_count == 0 and not unchanged_urls:
                    _cleanup()
                    raise CrawlerException(
                        f"Crawl failed for {url}: crawler service at "
                        f"{self.base_url} returned no pages "
                        f"(failed_count={failed_count}, outcome={outcome})"
                    )

                if download_files and file_links:
                    await self._download_files(
                        session,
                        file_links,
                        tmp_dir_obj.name,
                        crawl_host=host_of(url),
                        http_user=http_user,
                        http_pass=http_pass,
                        tenant_crawler_settings=tenant_crawler_settings,
                    )

            def _iter_pages() -> Iterable[CrawledPage]:
                with open(spool_path) as f:
                    for line in f:
                        jsonl = json.loads(line)
                        yield CrawledPage(**jsonl)

            def _iter_files() -> Iterable[Path]:
                return Path(tmp_dir_obj.name).iterdir()

            yield Crawl(
                pages=_iter_pages(),
                files=_iter_files(),
                is_partial=is_partial,
                termination_reason=termination_reason,
                pages_count=pages_count,
                unchanged_urls=unchanged_urls,
            )

        finally:
            _cleanup()

    @staticmethod
    def _count_spool_lines(spool_path: str) -> int:
        try:
            if os.stat(spool_path).st_size == 0:
                return 0
            with open(spool_path) as f:
                return sum(1 for _ in f)
        except OSError:
            return 0


def create_crawler() -> RemoteCrawler:
    """Container factory for the crawler.

    Crawl execution is fully delegated to the external crawler service; there
    is no in-process fallback. A missing CRAWLER_SERVICE_URL fails the crawl
    job with a clear message instead of crashing at import time.
    """
    from eneo.main.config import get_settings

    settings = get_settings()
    if not settings.crawler_service_url:
        raise CrawlerException(
            "CRAWLER_SERVICE_URL is not configured; crawling requires the "
            "external crawler service"
        )
    return RemoteCrawler(
        base_url=settings.crawler_service_url,
        api_key=settings.crawler_service_api_key,
    )
