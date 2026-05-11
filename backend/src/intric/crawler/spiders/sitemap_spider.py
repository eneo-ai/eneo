"""Sitemap spider extensions.

This module mirrors Scrapy's SitemapSpider parsing loop so URLSET entries can
emit source-retention feed items instead of requests when lastmod source-skip is
enabled. Keep the upstream Scrapy sitemap API smoke test in sync with this file.
"""

import importlib
import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from re import Pattern
from typing import Protocol, cast
from urllib.parse import urlparse

import scrapy
from scrapy.http import Response
from typing_extensions import override

from intric.crawler.parse_html import parse_response

logger = logging.getLogger(__name__)


class _RequestFactory(Protocol):
    def __call__(
        self,
        url: str,
        callback: Callable[..., object] | None = None,
    ) -> object: ...


class _SitemapDocument(Protocol):
    type: str

    def __iter__(self) -> Iterator[dict[str, object]]: ...


class _SitemapFactory(Protocol):
    def __call__(self, xmltext: str) -> _SitemapDocument: ...


class _SitemapUrlsFromRobots(Protocol):
    def __call__(self, text: str, *, base_url: str | None = None) -> Iterable[str]: ...


_scrapy_sitemap = importlib.import_module("scrapy.utils.sitemap")
_Request = cast(_RequestFactory, getattr(scrapy, "Request"))
_Sitemap = cast(_SitemapFactory, getattr(_scrapy_sitemap, "Sitemap"))
_sitemap_urls_from_robots = cast(
    _SitemapUrlsFromRobots,
    getattr(_scrapy_sitemap, "sitemap_urls_from_robots"),
)


@dataclass(frozen=True, slots=True)
class SourceRetainedUrl:
    url: str


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_sitemap_lastmod(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None

    normalized_value = value.strip()
    if not normalized_value:
        return None

    if normalized_value.endswith("Z"):
        normalized_value = f"{normalized_value[:-1]}+00:00"

    try:
        return _normalize_datetime(datetime.fromisoformat(normalized_value))
    except ValueError:
        return None


def _iter_sitemap_locs(
    entries: Iterable[dict[str, object]],
    *,
    include_alternate: bool,
) -> Iterator[str]:
    for entry in entries:
        loc = entry.get("loc")
        if isinstance(loc, str):
            yield loc

        alternate = entry.get("alternate")
        if include_alternate and isinstance(alternate, list):
            for alternate_loc in cast(list[object], alternate):
                if isinstance(alternate_loc, str):
                    yield alternate_loc


class SitemapSpider(scrapy.spiders.SitemapSpider):  # type: ignore[attr-defined]
    name = "sitemapspider"
    sitemap_alternate_links: bool
    _follow: list[Pattern[str]]
    _cbs: list[tuple[Pattern[str], Callable[[Response], object]]]

    def __init__(
        self,
        sitemap_url: str,
        http_user: str | None = None,
        http_pass: str | None = None,
        lastmod_skip_cutoff: datetime | None = None,
        lastmod_skip_allowed_urls: Iterable[str] | None = None,
        *args: object,
        **kwargs: object,
    ) -> None:
        self.sitemap_urls = [sitemap_url]
        self._lastmod_skip_cutoff = (
            _normalize_datetime(lastmod_skip_cutoff)
            if lastmod_skip_cutoff is not None
            else None
        )
        self._lastmod_skip_allowed_urls = frozenset(lastmod_skip_allowed_urls or ())
        self._source_retained_urls: set[str] = set()

        # Set up basic authentication if provided
        if http_user and http_pass:
            parsed_uri = urlparse(sitemap_url)
            self.http_user = http_user
            self.http_pass = http_pass
            self.http_auth_domain = parsed_uri.netloc

        super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownMemberType]  # Scrapy spider __init__ is untyped

    @override
    def parse(self, response: Response):
        return parse_response(response)

    def _parse_sitemap(self, response: Response):
        if response.url.endswith("/robots.txt"):
            for url in _sitemap_urls_from_robots(response.text, base_url=response.url):
                yield _Request(url, callback=self._parse_sitemap)
            return

        get_sitemap_body = cast(
            Callable[[Response], bytes | None],
            getattr(super(), "_get_sitemap_body"),
        )
        body = get_sitemap_body(response)
        if body is None:
            logger.warning(
                "Ignoring invalid sitemap: %(response)s",
                {"response": response},
                extra={"spider": self},
            )
            return

        sitemap = _Sitemap(cast(str, body))
        if sitemap.type == "sitemapindex":
            for loc in _iter_sitemap_locs(
                sitemap,
                include_alternate=self.sitemap_alternate_links,
            ):
                if any(pattern.search(loc) for pattern in self._follow):
                    yield _Request(loc, callback=self._parse_sitemap)
            return

        if sitemap.type != "urlset":
            return

        for entry in sitemap:
            retained_url = self._source_retained_url_for_entry(entry)
            if retained_url is not None:
                if self._mark_source_retained_url(retained_url):
                    yield SourceRetainedUrl(url=retained_url)
                continue

            for loc in _iter_sitemap_locs(
                [entry], include_alternate=self.sitemap_alternate_links
            ):
                for rule, callback in self._cbs:
                    if rule.search(loc):
                        yield _Request(loc, callback=callback)
                        break

    @property
    def source_retained_urls(self) -> frozenset[str]:
        return frozenset(self._source_retained_urls)

    def _source_retained_url_for_entry(
        self,
        entry: dict[str, object],
    ) -> str | None:
        loc = entry.get("loc")
        if not isinstance(loc, str):
            return None

        if self._lastmod_skip_cutoff is None:
            return None
        if loc not in self._lastmod_skip_allowed_urls:
            return None

        parsed_lastmod = _parse_sitemap_lastmod(entry.get("lastmod"))
        if parsed_lastmod is None:
            return None

        if parsed_lastmod > self._lastmod_skip_cutoff:
            return None

        return loc

    def _mark_source_retained_url(self, url: str) -> bool:
        if url in self._source_retained_urls:
            return False

        self._source_retained_urls.add(url)
        return True
