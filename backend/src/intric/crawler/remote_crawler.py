"""Crawl execution delegated to the external crawler service.

Eneo owns crawl administration (websites, schedules, run history, circuit
breaker, slots) but never executes crawls in-process: the crawl is POSTed to
the crawler service, which streams results back as NDJSON events:

    {"type": "page", "url": ..., "title": ..., "content": ..., "file_links": [...]}
    {"type": "failed", "url": ..., "status": ...}
    {"type": "done", "outcome": {...}}

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
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any, Callable, Coroutine, Iterable, Optional, cast
from urllib.parse import unquote, urlparse

import aiohttp

from intric.crawler.models import Crawl, CrawledPage
from intric.main.exceptions import CrawlerException, CrawlTimeoutError
from intric.tenants.crawler_settings_helper import get_crawler_setting
from intric.websites.domain.crawl_run import CrawlType

logger = logging.getLogger(__name__)

# Margin on top of the service-side max_seconds before the client gives up
# on the stream; the service is expected to terminate the crawl itself.
_CLIENT_TIMEOUT_MARGIN_SECONDS = 120

# Connect timeout for opening the stream; the stream itself has no total
# timeout (a crawl legitimately runs for hours).
_CONNECT_TIMEOUT_SECONDS = 30

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
    ) -> tuple[int, int, list[str], dict[str, Any] | None]:
        """Consume the NDJSON stream into the spool file.

        Returns (pages_count, failed_count, file_links, outcome).
        """
        request_body = {
            "url": url,
            "crawl_type": crawl_type.value,
            "http_auth": (
                {"username": http_user, "password": http_pass}
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

        pages_count = 0
        failed_count = 0
        file_links: list[str] = []
        seen_links: set[str] = set()
        outcome: dict[str, Any] | None = None
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
                        page_url = event.get("url")
                        content = event.get("content") or event.get("raw_text") or ""
                        if not page_url:
                            continue
                        spool.write(
                            json.dumps(
                                {
                                    "url": page_url,
                                    "title": event.get("title") or page_url,
                                    "content": content,
                                }
                            )
                            + "\n"
                        )
                        pages_count += 1
                        if download_files:
                            raw_links: list[object] = event.get("file_links") or []
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
                    elif event_type == "failed":
                        failed_count += 1
                    elif event_type == "done":
                        outcome = event.get("outcome") or {}
                    # Other event types (unchanged, robots, ...) are tolerated
                    # and ignored: the worker has no use for them today.

        logger.info(
            "Crawler service stream consumed: url=%s events=%s outcome=%s",
            url,
            event_counts or "none",
            outcome,
        )
        return pages_count, failed_count, file_links, outcome

    async def _download_files(
        self,
        session: aiohttp.ClientSession,
        file_links: list[str],
        files_dir: str,
        *,
        http_user: str | None,
        http_pass: str | None,
        tenant_crawler_settings: dict[str, Any] | None,
    ) -> None:
        """Fetch linked files into the temp dir (best effort, per-file).

        The crawler service never transfers binaries; the worker fetches them
        directly so the existing hash-skip + TextExtractor loop applies.
        """
        max_size = get_crawler_setting("download_max_size", tenant_crawler_settings)
        timeout_seconds = get_crawler_setting(
            "download_timeout", tenant_crawler_settings
        )
        auth = (
            aiohttp.BasicAuth(http_user, http_pass) if http_user and http_pass else None
        )
        taken: set[str] = set()

        for index, link_url in enumerate(file_links):
            target = Path(files_dir) / _filename_for_link(link_url, taken, index)
            try:
                async with session.get(
                    link_url,
                    auth=auth,
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
    ):
        """Same contract as Crawler.crawl: yields a Crawl with file-backed
        iterators after the (remote) crawl finished, salvaging partial results
        on timeout or stream interruption."""
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
                        )
                    if outcome and outcome.get("termination_reason") not in (
                        None,
                        "completed",
                    ):
                        # Service ended the crawl early (its own max_seconds /
                        # max_pages); pages received so far are valid
                        is_partial = True
                        termination_reason = str(outcome["termination_reason"])
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
                    # spool, like any other early termination.
                    pages_count = self._count_spool_lines(spool_path)
                    if pages_count == 0:
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
                    if pages_count == 0:
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

                if pages_count == 0:
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
    from intric.main.config import get_settings

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
