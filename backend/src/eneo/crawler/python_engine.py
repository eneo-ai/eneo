"""Async in-process Python crawl engine.

This module intentionally has no persistence or scheduling knowledge. It can run
inside Eneo's existing worker or a dedicated crawl worker using the same image.
"""

import asyncio
import hashlib
import ipaddress
import logging
import re
import shutil
import socket
import unicodedata
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from itertools import islice
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from time import monotonic
from typing import TypeVar
from urllib.parse import unquote, urlsplit
from urllib.robotparser import RobotFileParser

import aiofiles
import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult
from aiohttp.resolver import DefaultResolver

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
    is_page_link,
    is_same_origin,
    normalize_url,
)
from eneo.crawler.sitemap import (
    InvalidSitemap,
    ParsedSitemap,
    SitemapEntry,
    SitemapSnapshot,
    parse_sitemap,
    snapshot_sitemap,
)
from eneo.websites.domain.crawl_run import CrawlType

logger = logging.getLogger(__name__)

_USER_AGENT = "EneoCrawler/1.0"
_RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
_FILENAME_SANITIZE = re.compile(r"[^\w.-]+")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 10
_MAX_FILENAME_BYTES = 200
_MAX_SUFFIX_BYTES = 16
_CRAWL_TEMP_PREFIX = "eneo-crawl-"

_ResponseResult = TypeVar("_ResponseResult")
_RobotsLookup = Callable[[str], Awaitable[RobotFileParser | None]]

_process_capacity: asyncio.Semaphore | None = None
_process_capacity_loop: asyncio.AbstractEventLoop | None = None
_process_capacity_limit: int | None = None


def cleanup_orphaned_crawl_directories(temp_root: Path | None = None) -> int:
    """Remove abandoned workspaces from a temp root private to this worker."""

    root = temp_root or Path(gettempdir())
    removed = 0
    for path in root.glob(f"{_CRAWL_TEMP_PREFIX}*"):
        try:
            if path.is_symlink() or not path.is_dir():
                continue
            shutil.rmtree(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning(
                "Abandoned crawler workspace could not be removed",
                extra={"workspace": path.name, "errno": exc.errno},
            )
            continue
        removed += 1
    return removed


@dataclass(frozen=True, slots=True)
class _FetchResult:
    event: PageCrawled | PageFailed | PageUnchanged
    links: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _FetchHandoff:
    pass


class _ResponseTooLarge(Exception):
    pass


class _UnsafeTarget(aiohttp.ClientError):
    pass


class _RedirectRejected(aiohttp.ClientError):
    pass


class _RobotsDisallowed(aiohttp.ClientError):
    pass


class _RedirectHandedOff(Exception):
    pass


def _terminal_page_owner(owner: str, handoffs: dict[str, str]) -> str:
    """Resolve and compress an acyclic chain of fetch-URL owners."""
    path: list[str] = []
    while owner in handoffs:
        path.append(owner)
        owner = handoffs[owner]
    for previous_owner in path:
        handoffs[previous_owner] = owner
    return owner


def _request_failure_reason(exc: BaseException) -> str:
    if isinstance(exc, _RobotsDisallowed):
        return "robots_disallowed"
    if isinstance(exc, _UnsafeTarget):
        return "unsafe_target"
    if isinstance(exc, _RedirectRejected):
        return "redirect_rejected"
    if isinstance(exc, asyncio.TimeoutError):
        return "request_timeout"
    if isinstance(exc, LookupError):
        return "response_decode_error"
    if isinstance(exc, aiohttp.ClientError):
        return "connection_error"
    return "request_failed"


def _filename_with_token(basename: str, token: str) -> str:
    suffix = Path(basename).suffix
    if len(suffix.encode("utf-8")) > _MAX_SUFFIX_BYTES:
        suffix = ""
    stem = basename.removesuffix(suffix) if suffix else basename
    reserved = len(f"_{token}{suffix}".encode("utf-8"))
    stem = (
        stem.encode("utf-8")[: _MAX_FILENAME_BYTES - reserved]
        .decode("utf-8", errors="ignore")
        .rstrip("._")
        or "download"
    )
    return f"{stem}_{token}{suffix}"


def _log_skipped_sitemap_entries(count: int) -> None:
    if count:
        logger.info(
            "Skipped known non-page sitemap entries",
            extra={"count": count},
        )


def _address_is_allowed(address: str, *, allow_private_network: bool) -> bool:
    if allow_private_network:
        return True
    try:
        parsed = ipaddress.ip_address(address)
        return parsed.is_global and not parsed.is_multicast
    except ValueError:
        return False


def _reject_disallowed_literal(url: str, *, allow_private_network: bool) -> None:
    hostname = urlsplit(url).hostname
    if hostname is None:
        raise _UnsafeTarget("Crawler target has no hostname")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not _address_is_allowed(hostname, allow_private_network=allow_private_network):
        raise _UnsafeTarget("Crawler target uses a non-global IP address")


class _SafeResolver(AbstractResolver):
    """Resolve hostnames while preventing DNS rebinding to local networks."""

    def __init__(self, *, allow_private_network: bool) -> None:
        self._delegate = DefaultResolver()
        self._allow_private_network = allow_private_network

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        results = await self._delegate.resolve(host, port, family)
        if not results or any(
            not _address_is_allowed(
                result["host"], allow_private_network=self._allow_private_network
            )
            for result in results
        ):
            raise _UnsafeTarget(
                f"Crawler target resolves to a non-global address: {host}"
            )
        return results

    async def close(self) -> None:
        await self._delegate.close()


def _process_http_capacity(limit: int) -> asyncio.Semaphore:
    """Return the HTTP semaphore shared by every crawl container in this process."""

    global _process_capacity
    global _process_capacity_limit
    global _process_capacity_loop

    loop = asyncio.get_running_loop()
    if _process_capacity is None or _process_capacity_loop is not loop:
        _process_capacity = asyncio.Semaphore(limit)
        _process_capacity_loop = loop
        _process_capacity_limit = limit
    elif _process_capacity_limit != limit:
        logger.warning(
            "Ignoring crawler HTTP capacity change after process initialization",
            extra={"active_limit": _process_capacity_limit, "requested_limit": limit},
        )
    return _process_capacity


class PythonCrawlEngine:
    """Bounded HTTP crawler implemented on Eneo's existing Python runtime."""

    def __init__(
        self,
        *,
        global_concurrency: int = 20,
        allow_private_network: bool = False,
    ) -> None:
        if global_concurrency <= 0:
            raise ValueError("global_concurrency must be greater than zero")
        self._global_concurrency = global_concurrency
        self._allow_private_network = allow_private_network

    @property
    def _capacity(self) -> asyncio.Semaphore:
        return _process_http_capacity(self._global_concurrency)

    async def crawl(self, request: CrawlRequest) -> AsyncGenerator[CrawlEvent, None]:
        seed_url = normalize_url(request.url)
        if seed_url is None:
            raise ValueError(f"Unsupported crawl URL: {request.url}")

        origin_authorization = (
            aiohttp.encode_basic_auth(request.http_user, request.http_pass or "")
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
        file_links_truncated = False
        sitemap_snapshot: SitemapSnapshot | None = None
        frontier: deque[str]
        page_owners: dict[str, str]
        owner_handoffs: dict[str, str] = {}
        follow_page_links = request.crawl_type == CrawlType.CRAWL
        page_links_truncated = follow_page_links and request.conditional_gets_truncated
        validators: dict[str, ConditionalGet] = {}
        for hint in request.conditional_gets:
            normalized = normalize_url(hint.url)
            if normalized is None or normalized in validators:
                continue
            if len(validators) >= request.limits.max_items:
                if follow_page_links:
                    page_links_truncated = True
                break
            validators[normalized] = hint

        files_dir: TemporaryDirectory[str] | None = None
        try:
            connector = aiohttp.TCPConnector(
                resolver=_SafeResolver(
                    allow_private_network=self._allow_private_network
                )
            )
            async with aiohttp.ClientSession(
                headers=headers,
                timeout=timeout,
                connector=connector,
            ) as session:
                robots_by_origin: dict[str, RobotFileParser | None] = {}
                robots_lock = asyncio.Lock()

                async def robots_for_url(url: str) -> RobotFileParser | None:
                    if not request.obey_robots:
                        return None
                    origin = (
                        urlsplit(url)._replace(path="", query="", fragment="").geturl()
                    )
                    # The request boundary checks scope first, so this cache
                    # contains only the seed origin and its permitted HTTPS upgrade.
                    async with robots_lock:
                        if origin not in robots_by_origin:
                            loaded = await self._load_robots(
                                session, url, seed_url, request, origin_authorization
                            )
                            policy = loaded[0] if loaded is not None else None
                            robots_by_origin[origin] = policy
                            if loaded is not None:
                                policy_origin = (
                                    urlsplit(loaded[1])
                                    ._replace(path="", query="", fragment="")
                                    .geturl()
                                )
                                # A custom redirect destination is policy for
                                # the requesting origin, not necessarily its host.
                                if loaded[1] == f"{policy_origin}/robots.txt":
                                    robots_by_origin.setdefault(policy_origin, policy)
                        return robots_by_origin[origin]

                try:
                    robots = await asyncio.wait_for(
                        robots_for_url(seed_url),
                        timeout=self._remaining_seconds(started_at, request),
                    )
                    if request.crawl_type == CrawlType.SITEMAP:
                        (
                            sitemap_urls,
                            sitemap_failures,
                            sitemap_snapshot,
                            sitemap_truncated,
                        ) = await asyncio.wait_for(
                            self._sitemap_urls(
                                session,
                                seed_url,
                                request,
                                origin_authorization,
                                robots_for_url,
                            ),
                            timeout=self._remaining_seconds(started_at, request),
                        )
                    else:
                        sitemap_urls = []
                        sitemap_failures = []
                        sitemap_truncated = False
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

                if request.crawl_type == CrawlType.SITEMAP:
                    for failure in sitemap_failures:
                        pages_failed += 1
                        yield failure
                    frontier = deque(sitemap_urls[: request.limits.max_items])
                    page_owners = {url: url for url in frontier}
                else:
                    frontier = deque([seed_url])
                    page_owners = {seed_url: seed_url}
                    for url in validators:
                        if url == seed_url or not is_in_scope(url, seed_url):
                            continue
                        if len(page_owners) >= request.limits.max_items:
                            page_links_truncated = True
                            break
                        page_owners[url] = url
                        frontier.append(url)

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
                # configured pacing instead delays refilling freed HTTP slots.
                per_crawl_concurrency = (
                    1 if robots_request_delay else request.limits.concurrency
                )
                link_reorder_window = per_crawl_concurrency * 2
                # A redirect alias hands its result slot to the fetch that owns the
                # target. One extra in-flight window permits useful replacements,
                # while bounding adversarial alias chains with existing limits.
                page_task_limit = request.limits.max_items + per_crawl_concurrency

                pending_pages: dict[
                    asyncio.Task[_FetchResult | _FetchHandoff], int
                ] = {}
                completed_links: dict[int, tuple[str, ...]] = {}
                next_sequence = 0
                next_result_sequence = 0
                page_tasks_started = 0
                refill_at: float | None = None

                def fill_page_capacity() -> None:
                    nonlocal next_sequence, page_tasks_started
                    while (
                        frontier
                        and len(pending_pages) < per_crawl_concurrency
                        and pages_seen + len(pending_pages) < request.limits.max_items
                        and page_tasks_started < page_task_limit
                        and (
                            not follow_page_links
                            or len(pending_pages) + len(completed_links)
                            < link_reorder_window
                        )
                    ):
                        url = frontier.popleft()
                        task = asyncio.create_task(
                            self._fetch(
                                session,
                                url,
                                seed_url,
                                request,
                                robots_for_url,
                                validators,
                                origin_authorization,
                                path_scope=follow_page_links,
                                page_owners=page_owners,
                                owner_handoffs=owner_handoffs,
                            )
                        )
                        pending_pages[task] = next_sequence
                        next_sequence += 1
                        page_tasks_started += 1

                crawl_timed_out = False
                fill_page_capacity()
                try:
                    while pending_pages or (
                        frontier
                        and pages_seen < request.limits.max_items
                        and page_tasks_started < page_task_limit
                    ):
                        if refill_at is not None and monotonic() >= refill_at:
                            refill_at = None
                        if (
                            frontier
                            and pages_seen + len(pending_pages)
                            < request.limits.max_items
                            and page_tasks_started < page_task_limit
                            and refill_at is None
                        ):
                            fill_page_capacity()

                        if not pending_pages:
                            if refill_at is None:
                                break
                            await asyncio.sleep(
                                min(
                                    max(0.0, refill_at - monotonic()),
                                    self._remaining_seconds(started_at, request),
                                )
                            )
                            continue

                        wait_timeout = self._remaining_seconds(started_at, request)
                        if refill_at is not None:
                            wait_timeout = min(
                                wait_timeout,
                                max(0.0, refill_at - monotonic()),
                            )
                        done, _ = await asyncio.wait(
                            pending_pages,
                            timeout=wait_timeout,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if not done:
                            if refill_at is not None and monotonic() >= refill_at:
                                continue
                            raise TimeoutError

                        completed = sorted(done, key=pending_pages.__getitem__)
                        for task in completed:
                            sequence = pending_pages.pop(task)
                            result = task.result()
                            if isinstance(result, _FetchHandoff):
                                if follow_page_links:
                                    completed_links[sequence] = ()
                                continue
                            if follow_page_links:
                                completed_links[sequence] = result.links
                            if isinstance(result.event, PageCrawled):
                                pages_crawled += 1
                                for file_url in result.event.file_links:
                                    if file_url in file_links:
                                        continue
                                    if len(file_links) >= request.limits.max_items:
                                        file_links_truncated = True
                                        break
                                    file_links.add(file_url)
                            elif isinstance(result.event, PageUnchanged):
                                pages_unchanged += 1
                            else:
                                pages_failed += 1
                            pages_seen += 1
                            yield result.event

                        while (
                            follow_page_links
                            and next_result_sequence in completed_links
                        ):
                            links = completed_links.pop(next_result_sequence)
                            next_result_sequence += 1
                            for discovered_url in links:
                                if discovered_url in page_owners or not is_in_scope(
                                    discovered_url, seed_url
                                ):
                                    continue
                                if (
                                    pages_seen + len(pending_pages) + len(frontier)
                                    >= page_task_limit
                                ):
                                    page_links_truncated = True
                                    break
                                page_owners[discovered_url] = discovered_url
                                frontier.append(discovered_url)

                        if (
                            request_delay
                            and frontier
                            and len(pending_pages) < per_crawl_concurrency
                            and page_tasks_started < page_task_limit
                            and refill_at is None
                        ):
                            refill_at = monotonic() + request_delay
                except TimeoutError:
                    crawl_timed_out = True
                finally:
                    for task in pending_pages:
                        task.cancel()
                    await asyncio.gather(*pending_pages, return_exceptions=True)

                if crawl_timed_out:
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

                remaining_file_items = max(
                    request.limits.max_items - pages_seen,
                    0,
                )
                if len(file_links) > remaining_file_items:
                    file_links_truncated = True

                item_limit_reached = (
                    bool(frontier)
                    or sitemap_truncated
                    or page_links_truncated
                    or file_links_truncated
                )
                termination_reason = "item_limit" if item_limit_reached else None

                if request.download_files and file_links and remaining_file_items:
                    files_dir = TemporaryDirectory(prefix=_CRAWL_TEMP_PREFIX)
                    try:
                        async for result in self._download_files(
                            session=session,
                            file_links=file_links,
                            scope_url=seed_url,
                            request=request,
                            directory=Path(files_dir.name),
                            origin_authorization=origin_authorization,
                            robots=robots_for_url,
                            started_at=started_at,
                            max_items=remaining_file_items,
                        ):
                            if isinstance(result, FileDownloaded):
                                files_downloaded += 1
                            else:
                                files_failed += 1
                            yield result
                    except TimeoutError:
                        termination_reason = "timeout"

            yield CrawlFinished(
                status="partial" if termination_reason else "completed",
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
                reason=termination_reason,
            )
        finally:
            if files_dir is not None:
                files_dir.cleanup()

    async def _load_robots(
        self,
        session: aiohttp.ClientSession,
        seed_url: str,
        scope_url: str,
        request: CrawlRequest,
        origin_authorization: str | None,
    ) -> tuple[RobotFileParser, str] | None:
        if not request.obey_robots:
            return None
        parsed = urlsplit(seed_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            async with self._request_with_redirects(
                session,
                robots_url,
                scope_url,
                origin_authorization,
                path_scope=False,
                robots=None,  # Bootstrap the policy without recursively checking it.
            ) as (response, final_url):
                if response.status != 200:
                    return None
                body = await self._read_bounded(
                    response, request.limits.max_response_bytes
                )
                parser.set_url(final_url)
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            _ResponseTooLarge,
            LookupError,
        ):
            return None
        parser.parse(
            body.decode(response.charset or "utf-8", errors="replace").splitlines()
        )
        return parser, final_url

    async def _request_with_retries(
        self,
        session: aiohttp.ClientSession,
        url: str,
        scope_url: str,
        retries: int,
        origin_authorization: str | None,
        *,
        path_scope: bool,
        robots: _RobotsLookup | None,
        consume_response: Callable[
            [aiohttp.ClientResponse, str], Awaitable[_ResponseResult]
        ],
        validators: dict[str, ConditionalGet] | None = None,
        claim_redirect_target: Callable[[str], bool] | None = None,
    ) -> _ResponseResult:
        """Consume one response under capacity, retrying transport/status failures.

        The consumer may run once per attempt and must restart partial output cleanly.
        """
        attempts = retries + 1
        for attempt in range(attempts):
            try:
                async with self._request_with_redirects(
                    session,
                    url,
                    scope_url,
                    origin_authorization,
                    path_scope=path_scope,
                    robots=robots,
                    validators=validators,
                    claim_redirect_target=claim_redirect_target,
                ) as (response, final_url):
                    if (
                        response.status in _RETRYABLE_STATUSES
                        and attempt + 1 < attempts
                    ):
                        retry_delay = self._retry_delay(response, attempt)
                    else:
                        return await consume_response(response, final_url)
            except (_UnsafeTarget, _RedirectRejected, _RobotsDisallowed):
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt + 1 == attempts:
                    raise
                retry_delay = min(2**attempt, 10)

            # Backoff must not occupy one of the process-wide HTTP slots.
            await asyncio.sleep(retry_delay)

        raise AssertionError("retry loop exhausted without a result")

    async def _fetch(
        self,
        session: aiohttp.ClientSession,
        url: str,
        scope_url: str,
        request: CrawlRequest,
        robots: _RobotsLookup | None,
        validators: dict[str, ConditionalGet],
        origin_authorization: str | None,
        *,
        path_scope: bool,
        page_owners: dict[str, str],
        owner_handoffs: dict[str, str],
    ) -> _FetchResult | _FetchHandoff:
        redirect_chain = {url}

        def claim_redirect_target(target_url: str) -> bool:
            if target_url in redirect_chain:
                return True

            target_owner = page_owners.get(target_url)
            if target_owner is None:
                page_owners[target_url] = url
                redirect_chain.add(target_url)
                return True

            target_owner = _terminal_page_owner(target_owner, owner_handoffs)
            if target_owner == url:
                page_owners[target_url] = url
                redirect_chain.add(target_url)
                return True

            owner_handoffs[url] = target_owner
            return False

        async def consume_response(
            response: aiohttp.ClientResponse,
            final_url: str,
        ) -> _FetchResult:
            if response.status == 304:
                validator = validators.get(final_url)
                if validator is not None and (
                    validator.etag or validator.last_modified
                ):
                    return _FetchResult(PageUnchanged(url=final_url))
                # A 304 without a validator for this exact URL proves nothing
                # about stored content, especially after an alias redirects.
                return _FetchResult(
                    PageFailed(url=final_url, status_code=304, reason="http_304")
                )
            if response.status >= 400:
                return _FetchResult(
                    PageFailed(
                        url=final_url,
                        status_code=response.status,
                        reason=f"http_{response.status}",
                        retryable=response.status in _RETRYABLE_STATUSES,
                    )
                )

            body = await self._read_bounded(response, request.limits.max_response_bytes)
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
            scoped_file_links = (
                tuple(
                    file_url
                    for file_url in extracted.file_links
                    if is_same_origin(file_url, final_url, allow_https_upgrade=True)
                )
                if request.download_files
                else ()
            )
            return _FetchResult(
                PageCrawled(
                    url=final_url,
                    title=extracted.title,
                    content=extracted.content,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                    file_links=scoped_file_links,
                ),
                links=tuple(
                    link
                    for link in extracted.links
                    if is_same_origin(link, final_url, allow_https_upgrade=True)
                ),
            )

        try:
            return await self._request_with_retries(
                session,
                url,
                scope_url,
                request.limits.retries,
                origin_authorization,
                path_scope=path_scope,
                robots=robots,
                consume_response=consume_response,
                validators=validators,
                claim_redirect_target=claim_redirect_target,
            )
        except _RedirectHandedOff:
            return _FetchHandoff()
        except _ResponseTooLarge:
            return _FetchResult(PageFailed(url=url, reason="response_too_large"))
        except (
            _UnsafeTarget,
            _RedirectRejected,
            _RobotsDisallowed,
            LookupError,
        ) as exc:
            return _FetchResult(
                PageFailed(url=url, reason=_request_failure_reason(exc))
            )
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            return _FetchResult(
                PageFailed(
                    url=url,
                    reason=_request_failure_reason(exc),
                    retryable=True,
                )
            )

    async def _download_files(
        self,
        *,
        session: aiohttp.ClientSession,
        file_links: set[str],
        scope_url: str,
        request: CrawlRequest,
        directory: Path,
        origin_authorization: str | None,
        robots: _RobotsLookup | None,
        started_at: float,
        max_items: int,
    ) -> AsyncIterator[FileDownloaded | FileFailed]:
        """Download files concurrently without creating an unbounded task set."""

        urls = iter(islice(sorted(file_links), max_items))
        taken_names: set[str] = set()
        pending: set[asyncio.Task[FileDownloaded | FileFailed]] = set()

        def fill_capacity() -> None:
            while len(pending) < request.limits.concurrency:
                try:
                    file_url = next(urls)
                except StopIteration:
                    return
                pending.add(
                    asyncio.create_task(
                        self._download_file(
                            session,
                            file_url,
                            scope_url,
                            request,
                            directory,
                            taken_names,
                            origin_authorization,
                            robots,
                        )
                    )
                )

        fill_capacity()
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    timeout=self._remaining_seconds(started_at, request),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    raise TimeoutError

                # Refill before yielding so file processing by the consumer does
                # not unnecessarily leave HTTP capacity idle.
                results = [task.result() for task in done]
                fill_capacity()
                for result in results:
                    try:
                        yield result
                    finally:
                        if isinstance(result, FileDownloaded):
                            try:
                                result.path.unlink(missing_ok=True)
                            except OSError as exc:
                                logger.warning(
                                    "Processed crawl file could not be removed; "
                                    "workspace cleanup will retry",
                                    extra={
                                        "workspace": result.path.parent.name,
                                        "file": result.path.name,
                                        "errno": exc.errno,
                                    },
                                )
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def _download_file(
        self,
        session: aiohttp.ClientSession,
        url: str,
        scope_url: str,
        request: CrawlRequest,
        directory: Path,
        taken_names: set[str],
        origin_authorization: str | None,
        robots: _RobotsLookup | None,
    ) -> FileDownloaded | FileFailed:
        normalized = normalize_url(url)
        if normalized is None or not is_same_origin(
            normalized, scope_url, allow_https_upgrade=True
        ):
            return FileFailed(url=url, reason="file_out_of_scope")

        filename = self._filename_for_url(normalized, taken_names)
        target = directory / filename
        partial = target.with_name(f"{target.name}.part")

        async def consume_response(
            response: aiohttp.ClientResponse,
            final_url: str,
        ) -> FileDownloaded | FileFailed:
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
                        return FileFailed(url=final_url, reason="file_too_large")
                    await output.write(chunk)
            partial.replace(target)
            return FileDownloaded(
                url=final_url,
                filename=filename,
                path=target,
            )

        try:
            return await self._request_with_retries(
                session,
                normalized,
                scope_url,
                request.limits.retries,
                origin_authorization,
                path_scope=False,
                robots=robots,
                consume_response=consume_response,
            )
        except (_UnsafeTarget, _RedirectRejected, _RobotsDisallowed) as exc:
            return FileFailed(url=normalized, reason=_request_failure_reason(exc))
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            return FileFailed(
                url=normalized,
                reason=_request_failure_reason(exc),
                retryable=True,
            )
        finally:
            partial.unlink(missing_ok=True)

    @staticmethod
    def _filename_for_url(url: str, taken_names: set[str]) -> str:
        basename = (
            unicodedata.normalize("NFC", unquote(Path(urlsplit(url).path).name))
            or "download"
        )
        basename = _FILENAME_SANITIZE.sub("_", basename).strip("._") or "download"
        encoded = basename.encode("utf-8")
        if len(encoded) > _MAX_FILENAME_BYTES:
            digest = hashlib.sha256(encoded).hexdigest()[:8]
            basename = _filename_with_token(basename, digest)

        def is_available(candidate: str) -> bool:
            return (
                candidate not in taken_names and f"{candidate}.part" not in taken_names
            )

        if not is_available(basename):
            collision_source = basename
            digest = hashlib.sha256(url.encode()).hexdigest()[:8]
            for collision in range(len(taken_names) + 1):
                token = digest if collision == 0 else f"{digest}_{collision}"
                candidate = _filename_with_token(collision_source, token)
                if is_available(candidate):
                    basename = candidate
                    break
            else:
                raise AssertionError("bounded download filename search exhausted")

        taken_names.update((basename, f"{basename}.part"))
        return basename

    async def _sitemap_urls(
        self,
        session: aiohttp.ClientSession,
        sitemap_url: str,
        request: CrawlRequest,
        origin_authorization: str | None,
        robots: _RobotsLookup | None,
    ) -> tuple[list[str], list[PageFailed], SitemapSnapshot | None, bool]:
        sitemap_frontier = deque([sitemap_url])
        seen_sitemaps = {sitemap_url}
        page_urls: list[str] = []
        seen_pages: set[str] = set()
        failures: list[PageFailed] = []
        sitemap_entries: list[SitemapEntry] = []
        skipped_non_page_entries = 0
        ignored_entries = 0
        sitemap_truncated = False
        max_sitemap_documents = 100

        async def consume_response(
            response: aiohttp.ClientResponse,
            final_url: str,
        ) -> tuple[str, ParsedSitemap | PageFailed]:
            if response.status >= 400:
                return final_url, PageFailed(
                    url=final_url,
                    status_code=response.status,
                    reason=f"http_{response.status}",
                    retryable=response.status in _RETRYABLE_STATUSES,
                )
            body = await self._read_bounded(response, request.limits.max_response_bytes)
            return final_url, parse_sitemap(
                body,
                max_decompressed_bytes=request.limits.max_response_bytes,
            )

        while sitemap_frontier:
            current = sitemap_frontier.popleft()

            try:
                final_url, parsed_or_failure = await self._request_with_retries(
                    session,
                    current,
                    sitemap_url,
                    request.limits.retries,
                    origin_authorization,
                    path_scope=False,
                    robots=robots,
                    consume_response=consume_response,
                )
            except _ResponseTooLarge:
                failures.append(PageFailed(url=current, reason="sitemap_too_large"))
                continue
            except InvalidSitemap:
                failures.append(PageFailed(url=current, reason="invalid_sitemap"))
                continue
            except (_UnsafeTarget, _RedirectRejected, _RobotsDisallowed) as exc:
                failures.append(
                    PageFailed(url=current, reason=_request_failure_reason(exc))
                )
                continue
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                failures.append(
                    PageFailed(
                        url=current,
                        reason=_request_failure_reason(exc),
                        retryable=True,
                    )
                )
                continue

            if isinstance(parsed_or_failure, PageFailed):
                failures.append(parsed_or_failure)
                continue
            parsed = parsed_or_failure
            if not parsed.structurally_complete:
                failures.append(PageFailed(url=final_url, reason="invalid_sitemap"))

            if parsed.kind == "sitemapindex":
                for location in parsed.locations:
                    normalized = normalize_url(location, base_url=final_url)
                    if (
                        normalized is None
                        or not is_same_origin(
                            normalized, final_url, allow_https_upgrade=True
                        )
                        or normalized in seen_sitemaps
                    ):
                        ignored_entries += 1
                        continue
                    if len(seen_sitemaps) >= max_sitemap_documents:
                        ignored_entries += 1
                        sitemap_truncated = True
                        continue
                    seen_sitemaps.add(normalized)
                    sitemap_frontier.append(normalized)
                continue

            for original_entry in parsed.entries:
                location = original_entry.location
                normalized = normalize_url(location, base_url=final_url)
                if (
                    normalized is None
                    or not is_same_origin(
                        normalized, final_url, allow_https_upgrade=True
                    )
                    or normalized in seen_pages
                ):
                    ignored_entries += 1
                    continue
                if not is_page_link(normalized):
                    skipped_non_page_entries += 1
                    ignored_entries += 1
                    continue

                if len(page_urls) >= request.limits.max_items:
                    _log_skipped_sitemap_entries(skipped_non_page_entries)
                    return page_urls, failures, None, True
                seen_pages.add(normalized)
                page_urls.append(normalized)
                sitemap_entries.append(
                    SitemapEntry(
                        location=normalized,
                        last_modified=original_entry.last_modified,
                    )
                )

        _log_skipped_sitemap_entries(skipped_non_page_entries)
        # Only page candidates belong in the fingerprint. Asset-only sitemap
        # changes should not force a content recrawl. If every declared entry
        # was ignored, however, the sitemap is not proof that content vanished.
        snapshot_is_complete = (
            not failures
            and not sitemap_truncated
            and (bool(sitemap_entries) or ignored_entries == 0)
        )
        snapshot = snapshot_sitemap(sitemap_entries) if snapshot_is_complete else None
        return page_urls, failures, snapshot, sitemap_truncated

    @asynccontextmanager
    async def _request_with_redirects(
        self,
        session: aiohttp.ClientSession,
        url: str,
        scope_url: str,
        origin_authorization: str | None,
        *,
        path_scope: bool,
        robots: _RobotsLookup | None,
        validators: dict[str, ConditionalGet] | None = None,
        claim_redirect_target: Callable[[str], bool] | None = None,
    ) -> AsyncGenerator[tuple[aiohttp.ClientResponse, str], None]:
        current = normalize_url(url)
        if current is None:
            raise _RedirectRejected("invalid request URL")

        previous = scope_url
        for redirect_count in range(_MAX_REDIRECTS + 1):
            in_scope = (
                is_in_scope(current, scope_url)
                if path_scope
                else is_same_origin(current, scope_url, allow_https_upgrade=True)
            )
            if not in_scope or not is_same_origin(
                current, previous, allow_https_upgrade=True
            ):
                raise _RedirectRejected("redirect target is outside crawl scope")
            _reject_disallowed_literal(
                current, allow_private_network=self._allow_private_network
            )
            # Resolve the policy before holding HTTP capacity: loading robots
            # itself needs a slot, including after an HTTP-to-HTTPS redirect.
            policy = await robots(current) if robots is not None else None
            if policy is not None and not policy.can_fetch(_USER_AGENT, current):
                raise _RobotsDisallowed("request target is disallowed by robots.txt")
            if (
                redirect_count
                and claim_redirect_target is not None
                and not claim_redirect_target(current)
            ):
                raise _RedirectHandedOff

            request_authorization = (
                origin_authorization if is_same_origin(current, scope_url) else None
            )
            request_headers: dict[str, str] = {}
            validator = validators.get(current) if validators is not None else None
            if validator is not None and validator.etag:
                request_headers["If-None-Match"] = validator.etag
            if validator is not None and validator.last_modified:
                request_headers["If-Modified-Since"] = validator.last_modified
            if request_authorization is not None:
                request_headers["Authorization"] = request_authorization
            async with self._capacity:
                response = await session.get(
                    current,
                    allow_redirects=False,
                    headers=request_headers,
                )
                async with response:
                    if response.status not in _REDIRECT_STATUSES:
                        yield response, current
                        return
                    location = response.headers.get("Location")
            if not location:
                raise _RedirectRejected("redirect response has no Location header")
            if redirect_count >= _MAX_REDIRECTS:
                raise _RedirectRejected("redirect limit exceeded")
            redirected = normalize_url(location, base_url=current)
            if redirected is None:
                raise _RedirectRejected("invalid redirect URL")
            previous, current = current, redirected

        raise AssertionError("redirect loop exhausted without a result")

    @staticmethod
    def _remaining_seconds(started_at: float, request: CrawlRequest) -> float:
        remaining = request.limits.max_seconds - (monotonic() - started_at)
        if remaining <= 0:
            raise TimeoutError
        return remaining

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
