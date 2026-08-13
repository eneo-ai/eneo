"""Async in-process Python crawl engine.

This module intentionally has no persistence or scheduling knowledge. It can run
inside Eneo's existing worker or a dedicated crawl worker using the same image.
"""

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import monotonic
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import aiohttp

from eneo.crawler.engine import (
    ConditionalGet,
    CrawlEvent,
    CrawlFinished,
    CrawlRequest,
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
from eneo.crawler.sitemap import InvalidSitemap, parse_sitemap
from eneo.websites.domain.crawl_run import CrawlType

logger = logging.getLogger(__name__)

_USER_AGENT = "EneoCrawler/1.0"
_RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class _FetchResult:
    event: PageCrawled | PageFailed | PageUnchanged
    links: tuple[str, ...] = ()


class _ResponseTooLarge(Exception):
    pass


class PythonCrawlEngine:
    """Bounded HTTP crawler implemented on Eneo's existing Python runtime."""

    async def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]:
        seed_url = normalize_url(request.url)
        if seed_url is None:
            raise ValueError(f"Unsupported crawl URL: {request.url}")

        auth = (
            aiohttp.BasicAuth(request.http_user, request.http_pass or "")
            if request.http_user
            else None
        )
        timeout = aiohttp.ClientTimeout(total=request.limits.request_timeout_seconds)
        headers = {"User-Agent": _USER_AGENT, "Accept": "text/html,application/json"}
        started_at = monotonic()
        pages_crawled = 0
        pages_failed = 0
        pages_unchanged = 0
        pages_seen = 0
        frontier: deque[str]
        seen: set[str]
        follow_page_links = request.crawl_type == CrawlType.CRAWL
        validators = {
            normalized: hint
            for hint in request.conditional_gets
            if (normalized := normalize_url(hint.url)) is not None
        }

        async with aiohttp.ClientSession(
            auth=auth,
            headers=headers,
            timeout=timeout,
        ) as session:
            robots = await self._load_robots(session, seed_url, request)
            if request.crawl_type == CrawlType.SITEMAP:
                sitemap_urls, sitemap_failures = await self._sitemap_urls(
                    session, seed_url, request
                )
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
            try:
                while frontier and pages_seen < request.limits.max_pages:
                    remaining = request.limits.max_seconds - (monotonic() - started_at)
                    if remaining <= 0:
                        raise TimeoutError

                    batch_size = min(
                        request.limits.concurrency,
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

                    if request.limits.request_delay_seconds and frontier:
                        await asyncio.sleep(request.limits.request_delay_seconds)
            except TimeoutError:
                yield CrawlFinished(
                    status="partial",
                    pages_crawled=pages_crawled,
                    pages_failed=pages_failed,
                    pages_unchanged=pages_unchanged,
                    reason="timeout",
                )
                return

        yield CrawlFinished(
            status="completed",
            pages_crawled=pages_crawled,
            pages_failed=pages_failed,
            pages_unchanged=pages_unchanged,
        )

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
                request_headers: dict[str, str] = {}
                validator = validators.get(url)
                if validator is not None and validator.etag:
                    request_headers["If-None-Match"] = validator.etag
                if validator is not None and validator.last_modified:
                    request_headers["If-Modified-Since"] = validator.last_modified

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
                        await asyncio.sleep(self._retry_delay(response, attempt))
                        continue
                    if response.status == 304:
                        return _FetchResult(PageUnchanged(url=final_url))
                    if response.status >= 400:
                        return _FetchResult(
                            PageFailed(
                                url=final_url,
                                status_code=response.status,
                                reason=f"http_{response.status}",
                                retryable=response.status in _RETRYABLE_STATUSES,
                            )
                        )

                    body = await self._read_bounded(
                        response, request.limits.max_response_bytes
                    )
                    content_type = response.headers.get("Content-Type", "").lower()
                    text = body.decode(response.charset or "utf-8", errors="replace")
                    if "application/json" in content_type:
                        return _FetchResult(
                            PageCrawled(
                                url=final_url,
                                title=final_url,
                                content=text,
                                etag=response.headers.get("ETag"),
                                last_modified=response.headers.get("Last-Modified"),
                            )
                        )
                    if "html" not in content_type:
                        return _FetchResult(
                            PageFailed(
                                url=final_url,
                                status_code=response.status,
                                reason="unsupported_content_type",
                            )
                        )

                    extracted = extract_html(text, final_url)
                    return _FetchResult(
                        PageCrawled(
                            url=final_url,
                            title=extracted.title,
                            content=extracted.content,
                            etag=response.headers.get("ETag"),
                            last_modified=response.headers.get("Last-Modified"),
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

    async def _sitemap_urls(
        self,
        session: aiohttp.ClientSession,
        sitemap_url: str,
        request: CrawlRequest,
    ) -> tuple[list[str], list[PageFailed]]:
        sitemap_frontier = deque([sitemap_url])
        seen_sitemaps = {sitemap_url}
        page_urls: list[str] = []
        seen_pages: set[str] = set()
        failures: list[PageFailed] = []
        max_sitemap_documents = 100

        while sitemap_frontier and len(seen_sitemaps) <= max_sitemap_documents:
            current = sitemap_frontier.popleft()
            try:
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
                    if len(page_urls) >= request.limits.max_pages:
                        return page_urls, failures

        return page_urls, failures

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
