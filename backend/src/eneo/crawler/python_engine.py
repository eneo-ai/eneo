"""Async in-process Python crawl engine.

This module intentionally has no persistence or scheduling knowledge. It can run
inside Eneo's existing worker or a dedicated crawl worker using the same image.
"""

import asyncio
import hashlib
import logging
import re
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from urllib.parse import unquote, urlsplit
from urllib.robotparser import RobotFileParser

import aiofiles
import aiohttp

from eneo.crawler.engine import (
    ConditionalGet,
    CrawlEvent,
    CrawlFinished,
    CrawlRequest,
    FileDownloaded,
    FileFailed,
    PageCrawled,
    PageFailed,
    PageUnchanged,
)
from eneo.crawler.extraction import (
    extract_html,
    is_in_scope,
    is_same_origin,
    normalize_url,
)
from eneo.crawler.sitemap import (
    InvalidSitemap,
    SitemapEntry,
    SitemapSnapshot,
    parse_sitemap,
    snapshot_sitemap,
)
from eneo.websites.domain.crawl_run import CrawlType

logger = logging.getLogger(__name__)

_USER_AGENT = "EneoCrawler/1.0"
_RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
_FILENAME_SANITIZE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class _FetchResult:
    event: PageCrawled | PageFailed | PageUnchanged
    links: tuple[str, ...] = ()


class _ResponseTooLarge(Exception):
    pass


class PythonCrawlEngine:
    """Bounded HTTP crawler implemented on Eneo's existing Python runtime."""

    def __init__(self, *, global_concurrency: int = 20) -> None:
        if global_concurrency <= 0:
            raise ValueError("global_concurrency must be greater than zero")
        self._capacity = asyncio.Semaphore(global_concurrency)

    async def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]:
        seed_url = normalize_url(request.url)
        if seed_url is None:
            raise ValueError(f"Unsupported crawl URL: {request.url}")

        auth = (
            aiohttp.BasicAuth(request.http_user, request.http_pass or "")
            if request.http_user
            else None
        )
        timeout = aiohttp.ClientTimeout(
            total=request.limits.request_timeout_seconds,
            connect=min(
                request.limits.dns_timeout_seconds,
                request.limits.request_timeout_seconds,
            ),
        )
        headers = {"User-Agent": _USER_AGENT, "Accept": "text/html,application/json"}
        started_at = monotonic()
        pages_crawled = 0
        pages_failed = 0
        pages_unchanged = 0
        pages_seen = 0
        files_downloaded = 0
        files_failed = 0
        file_links: set[str] = set()
        sitemap_snapshot: SitemapSnapshot | None = None
        frontier: deque[str]
        seen: set[str]
        follow_page_links = request.crawl_type == CrawlType.CRAWL
        validators = {
            normalized: hint
            for hint in request.conditional_gets
            if (normalized := normalize_url(hint.url)) is not None
        }

        files_dir = TemporaryDirectory(prefix="eneo-crawl-")
        try:
            async with aiohttp.ClientSession(
                auth=auth,
                headers=headers,
                timeout=timeout,
            ) as session:
                robots = await self._load_robots(session, seed_url, request)
                if request.crawl_type == CrawlType.SITEMAP:
                    (
                        sitemap_urls,
                        sitemap_failures,
                        sitemap_snapshot,
                    ) = await self._sitemap_urls(session, seed_url, request)
                    for failure in sitemap_failures:
                        pages_failed += 1
                        yield failure
                    frontier = deque(sitemap_urls[: request.limits.max_pages])
                    seen = set(frontier)
                else:
                    known_urls = [
                        url
                        for url in validators
                        if url != seed_url and is_in_scope(url, seed_url)
                    ]
                    frontier = deque([seed_url, *known_urls])
                    seen = set(frontier)

                robots_delay = (
                    (robots.crawl_delay(_USER_AGENT) or robots.crawl_delay("*"))
                    if robots is not None
                    else None
                )
                robots_request_delay = float(robots_delay or 0)
                request_delay = max(
                    request.limits.request_delay_seconds,
                    robots_request_delay,
                )
                # A robots crawl-delay is a per-origin serial contract. Eneo's
                # configured pacing instead delays bounded concurrent batches.
                per_crawl_concurrency = (
                    1 if robots_request_delay else request.limits.concurrency
                )

                try:
                    while frontier and pages_seen < request.limits.max_pages:
                        remaining = request.limits.max_seconds - (
                            monotonic() - started_at
                        )
                        if remaining <= 0:
                            raise TimeoutError

                        batch_size = min(
                            per_crawl_concurrency,
                            request.limits.max_pages - pages_seen,
                            len(frontier),
                        )
                        urls = [frontier.popleft() for _ in range(batch_size)]
                        tasks = [
                            asyncio.create_task(
                                self._fetch(
                                    session,
                                    url,
                                    seed_url,
                                    request,
                                    robots,
                                    validators,
                                    path_scope=follow_page_links,
                                )
                            )
                            for url in urls
                        ]
                        try:
                            results = await asyncio.wait_for(
                                asyncio.gather(*tasks), timeout=remaining
                            )
                        except BaseException:
                            for task in tasks:
                                task.cancel()
                            await asyncio.gather(*tasks, return_exceptions=True)
                            raise

                        for result in results:
                            if isinstance(result.event, PageCrawled):
                                pages_crawled += 1
                                file_links.update(result.event.file_links)
                            elif isinstance(result.event, PageUnchanged):
                                pages_unchanged += 1
                            else:
                                pages_failed += 1
                            pages_seen += 1
                            yield result.event

                            if not follow_page_links:
                                continue
                            for discovered_url in result.links:
                                if discovered_url not in seen and is_in_scope(
                                    discovered_url, seed_url
                                ):
                                    seen.add(discovered_url)
                                    frontier.append(discovered_url)

                        if request_delay and frontier:
                            await asyncio.sleep(request_delay)
                except TimeoutError:
                    yield CrawlFinished(
                        status="partial",
                        pages_crawled=pages_crawled,
                        pages_failed=pages_failed,
                        pages_unchanged=pages_unchanged,
                        files_downloaded=files_downloaded,
                        files_failed=files_failed,
                        reason="timeout",
                    )
                    return

                if request.download_files and file_links:
                    taken_names: set[str] = set()
                    for file_url in sorted(file_links):
                        result = await self._download_file(
                            session,
                            file_url,
                            seed_url,
                            request,
                            Path(files_dir.name),
                            taken_names,
                        )
                        if isinstance(result, FileDownloaded):
                            files_downloaded += 1
                        else:
                            files_failed += 1
                        yield result

            yield CrawlFinished(
                status="completed",
                pages_crawled=pages_crawled,
                pages_failed=pages_failed,
                pages_unchanged=pages_unchanged,
                files_downloaded=files_downloaded,
                files_failed=files_failed,
                sitemap_fingerprint=(
                    sitemap_snapshot.fingerprint if sitemap_snapshot else None
                ),
                sitemap_entries=(
                    sitemap_snapshot.entry_count if sitemap_snapshot else 0
                ),
            )
        finally:
            files_dir.cleanup()

    async def _load_robots(
        self,
        session: aiohttp.ClientSession,
        seed_url: str,
        request: CrawlRequest,
    ) -> RobotFileParser | None:
        if not request.obey_robots:
            return None
        parsed = urlsplit(seed_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            async with self._capacity:
                async with session.get(robots_url) as response:
                    if response.status != 200:
                        return None
                    body = await self._read_bounded(
                        response, request.limits.max_response_bytes
                    )
        except (aiohttp.ClientError, asyncio.TimeoutError, _ResponseTooLarge):
            return None
        parser.parse(
            body.decode(response.charset or "utf-8", errors="replace").splitlines()
        )
        return parser

    async def _fetch(
        self,
        session: aiohttp.ClientSession,
        url: str,
        scope_url: str,
        request: CrawlRequest,
        robots: RobotFileParser | None,
        validators: dict[str, ConditionalGet],
        *,
        path_scope: bool,
    ) -> _FetchResult:
        if robots is not None and not robots.can_fetch(_USER_AGENT, url):
            return _FetchResult(PageFailed(url=url, reason="robots_disallowed"))

        attempts = request.limits.retries + 1
        for attempt in range(attempts):
            try:
                retry_delay: float | None = None
                request_headers: dict[str, str] = {}
                validator = validators.get(url)
                if validator is not None and validator.etag:
                    request_headers["If-None-Match"] = validator.etag
                if validator is not None and validator.last_modified:
                    request_headers["If-Modified-Since"] = validator.last_modified

                async with self._capacity:
                    async with session.get(
                        url, allow_redirects=True, headers=request_headers
                    ) as response:
                        final_url = normalize_url(str(response.url))
                        if final_url is None:
                            return _FetchResult(
                                PageFailed(
                                    url=url,
                                    status_code=response.status,
                                    reason="invalid_redirect_url",
                                )
                            )
                        in_scope = (
                            is_in_scope(final_url, scope_url)
                            if path_scope
                            else is_same_origin(final_url, scope_url)
                        )
                        if not in_scope:
                            return _FetchResult(
                                PageFailed(
                                    url=url,
                                    status_code=response.status,
                                    reason="redirect_out_of_scope",
                                )
                            )

                        if (
                            response.status in _RETRYABLE_STATUSES
                            and attempt + 1 < attempts
                        ):
                            retry_delay = self._retry_delay(response, attempt)
                        elif response.status == 304:
                            return _FetchResult(PageUnchanged(url=final_url))
                        elif response.status >= 400:
                            return _FetchResult(
                                PageFailed(
                                    url=final_url,
                                    status_code=response.status,
                                    reason=f"http_{response.status}",
                                    retryable=response.status in _RETRYABLE_STATUSES,
                                )
                            )

                        body = (
                            b""
                            if retry_delay is not None
                            else await self._read_bounded(
                                response, request.limits.max_response_bytes
                            )
                        )
                        content_type = response.headers.get("Content-Type", "").lower()
                        charset = response.charset or "utf-8"
                        response_status = response.status
                        response_etag = response.headers.get("ETag")
                        response_last_modified = response.headers.get("Last-Modified")

                # Retry backoff must not occupy one of the process-wide HTTP slots.
                if retry_delay is not None:
                    await asyncio.sleep(retry_delay)
                    continue

                text = body.decode(charset, errors="replace")
                if "application/json" in content_type:
                    return _FetchResult(
                        PageCrawled(
                            url=final_url,
                            title=final_url,
                            content=text,
                            etag=response_etag,
                            last_modified=response_last_modified,
                        )
                    )
                if "html" not in content_type:
                    return _FetchResult(
                        PageFailed(
                            url=final_url,
                            status_code=response_status,
                            reason="unsupported_content_type",
                        )
                    )

                extracted = extract_html(text, final_url)
                return _FetchResult(
                    PageCrawled(
                        url=final_url,
                        title=extracted.title,
                        content=extracted.content,
                        etag=response_etag,
                        last_modified=response_last_modified,
                        file_links=(
                            extracted.file_links if request.download_files else ()
                        ),
                    ),
                    links=extracted.links,
                )

            except _ResponseTooLarge:
                return _FetchResult(PageFailed(url=url, reason="response_too_large"))
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt + 1 == attempts:
                    return _FetchResult(
                        PageFailed(
                            url=url,
                            reason=type(exc).__name__,
                            retryable=True,
                        )
                    )
                await asyncio.sleep(min(2**attempt, 10))

        raise AssertionError("retry loop exhausted without a result")

    async def _download_file(
        self,
        session: aiohttp.ClientSession,
        url: str,
        scope_url: str,
        request: CrawlRequest,
        directory: Path,
        taken_names: set[str],
    ) -> FileDownloaded | FileFailed:
        normalized = normalize_url(url)
        if normalized is None or not is_same_origin(normalized, scope_url):
            return FileFailed(url=url, reason="file_out_of_scope")

        filename = self._filename_for_url(normalized, taken_names)
        target = directory / filename
        partial = target.with_suffix(f"{target.suffix}.part")
        try:
            async with self._capacity:
                async with session.get(normalized, allow_redirects=True) as response:
                    final_url = normalize_url(str(response.url))
                    if final_url is None or not is_same_origin(final_url, scope_url):
                        return FileFailed(
                            url=normalized,
                            status_code=response.status,
                            reason="file_redirect_out_of_scope",
                        )
                    if response.status >= 400:
                        return FileFailed(
                            url=final_url,
                            status_code=response.status,
                            reason=f"http_{response.status}",
                            retryable=response.status in _RETRYABLE_STATUSES,
                        )
                    if (
                        response.content_length is not None
                        and response.content_length > request.limits.max_file_bytes
                    ):
                        return FileFailed(url=final_url, reason="file_too_large")

                    written = 0
                    async with aiofiles.open(partial, "wb") as output:
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            written += len(chunk)
                            if written > request.limits.max_file_bytes:
                                return FileFailed(
                                    url=final_url, reason="file_too_large"
                                )
                            await output.write(chunk)
                    partial.replace(target)
                    return FileDownloaded(
                        url=final_url,
                        filename=filename,
                        path=target,
                    )
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            return FileFailed(
                url=normalized,
                reason=type(exc).__name__,
                retryable=True,
            )
        finally:
            partial.unlink(missing_ok=True)

    @staticmethod
    def _filename_for_url(url: str, taken_names: set[str]) -> str:
        basename = unquote(Path(urlsplit(url).path).name) or "download"
        basename = _FILENAME_SANITIZE.sub("_", basename).strip("._") or "download"
        encoded = basename.encode("utf-8")
        if len(encoded) > 200:
            suffix = Path(basename).suffix
            digest = hashlib.sha256(encoded).hexdigest()[:8]
            available = 200 - len(suffix.encode("utf-8")) - len(digest) - 1
            stem = (
                Path(basename)
                .stem.encode("utf-8")[:available]
                .decode("utf-8", errors="ignore")
            )
            basename = f"{stem}_{digest}{suffix}"
        if basename in taken_names:
            basename = f"{hashlib.sha256(url.encode()).hexdigest()[:8]}_{basename}"
        taken_names.add(basename)
        return basename

    async def _sitemap_urls(
        self,
        session: aiohttp.ClientSession,
        sitemap_url: str,
        request: CrawlRequest,
    ) -> tuple[list[str], list[PageFailed], SitemapSnapshot | None]:
        sitemap_frontier = deque([sitemap_url])
        seen_sitemaps = {sitemap_url}
        page_urls: list[str] = []
        seen_pages: set[str] = set()
        failures: list[PageFailed] = []
        sitemap_entries: list[SitemapEntry] = []
        max_sitemap_documents = 100

        while sitemap_frontier and len(seen_sitemaps) <= max_sitemap_documents:
            current = sitemap_frontier.popleft()
            try:
                async with self._capacity:
                    async with session.get(current, allow_redirects=True) as response:
                        final_url = normalize_url(str(response.url))
                        if (
                            response.status >= 400
                            or final_url is None
                            or not is_same_origin(final_url, sitemap_url)
                        ):
                            failures.append(
                                PageFailed(
                                    url=current,
                                    status_code=response.status,
                                    reason="sitemap_fetch_failed",
                                )
                            )
                            continue
                        body = await self._read_bounded(
                            response, request.limits.max_response_bytes
                        )
                        parsed = parse_sitemap(
                            body,
                            max_decompressed_bytes=request.limits.max_response_bytes,
                        )
            except _ResponseTooLarge:
                failures.append(PageFailed(url=current, reason="sitemap_too_large"))
                continue
            except InvalidSitemap as exc:
                failures.append(PageFailed(url=current, reason=str(exc)))
                continue
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                failures.append(
                    PageFailed(url=current, reason=type(exc).__name__, retryable=True)
                )
                continue

            if parsed.kind == "sitemapindex":
                for location in parsed.locations:
                    normalized = normalize_url(location, base_url=final_url)
                    if (
                        normalized is not None
                        and is_same_origin(normalized, sitemap_url)
                        and normalized not in seen_sitemaps
                        and len(seen_sitemaps) < max_sitemap_documents
                    ):
                        seen_sitemaps.add(normalized)
                        sitemap_frontier.append(normalized)
                continue

            for location in parsed.locations:
                normalized = normalize_url(location, base_url=final_url)
                if (
                    normalized is not None
                    and is_same_origin(normalized, sitemap_url)
                    and normalized not in seen_pages
                ):
                    seen_pages.add(normalized)
                    page_urls.append(normalized)
                    original_entry = next(
                        entry for entry in parsed.entries if entry.location == location
                    )
                    sitemap_entries.append(
                        SitemapEntry(
                            location=normalized,
                            last_modified=original_entry.last_modified,
                        )
                    )
                    if len(page_urls) >= request.limits.max_pages:
                        return page_urls, failures, None

        snapshot = snapshot_sitemap(sitemap_entries) if not failures else None
        return page_urls, failures, snapshot

    async def probe_sitemap(self, request: CrawlRequest) -> SitemapSnapshot | None:
        if request.crawl_type != CrawlType.SITEMAP:
            return None
        seed_url = normalize_url(request.url)
        if seed_url is None:
            return None
        auth = (
            aiohttp.BasicAuth(request.http_user, request.http_pass or "")
            if request.http_user
            else None
        )
        timeout = aiohttp.ClientTimeout(
            total=request.limits.request_timeout_seconds,
            connect=min(
                request.limits.dns_timeout_seconds,
                request.limits.request_timeout_seconds,
            ),
        )
        async with aiohttp.ClientSession(
            auth=auth,
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
        ) as session:
            _, failures, snapshot = await self._sitemap_urls(session, seed_url, request)
        return None if failures else snapshot

    @staticmethod
    async def _read_bounded(response: aiohttp.ClientResponse, max_bytes: int) -> bytes:
        if response.content_length is not None and response.content_length > max_bytes:
            raise _ResponseTooLarge
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.content.iter_chunked(64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise _ResponseTooLarge
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _retry_delay(response: aiohttp.ClientResponse, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 30.0)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    return min(
                        max(
                            retry_at.timestamp()
                            - datetime.now(timezone.utc).timestamp(),
                            0.0,
                        ),
                        30.0,
                    )
                except (TypeError, ValueError, OverflowError):
                    pass
        return min(2**attempt, 10)
