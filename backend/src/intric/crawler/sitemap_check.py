"""Sitemap fingerprinting for the scheduled-crawl short-circuit.

Fetches a sitemap (urlset, or sitemapindex with one level of sub-sitemaps),
extracts (url, lastmod) entries, and reduces them to a SHA-256 fingerprint.
A scheduled sitemap crawl whose fingerprint matches the one stored from the
last completed crawl is skipped before any page is fetched.

Deliberately conservative: any fetch or parse failure, an oversized or
nested index, or a sitemap without lastmod values yields a probe that can
never justify a skip — the crawl then proceeds as if the probe had not run.
"""

import asyncio
import hashlib
import html
import logging
import re
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

_FETCH_TIMEOUT_SECONDS = 20
# Hard ceiling on one probe including all sub-sitemap fetches; a probe must
# stay cheap relative to the crawl it can save
_PROBE_BUDGET_SECONDS = 120
_MAX_FETCH_BYTES = 16 * 1024 * 1024
# Indexes larger than this are cheaper to crawl with conditional GETs than
# to fingerprint on every schedule tick
_MAX_SUB_SITEMAPS = 50

_IS_INDEX = re.compile(r"<sitemapindex\b", re.IGNORECASE)
_SITEMAP_BLOCK = re.compile(r"<sitemap\b[\s\S]*?</sitemap>", re.IGNORECASE)
_URL_BLOCK = re.compile(r"<url\b[\s\S]*?</url>", re.IGNORECASE)
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_LASTMOD = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.IGNORECASE)


@dataclass(frozen=True)
class SitemapProbe:
    fingerprint: str
    entry_count: int
    lastmod_count: int

    @property
    def supports_skip(self) -> bool:
        """Without lastmod values the fingerprint only reflects the URL set,
        not content changes, so it must never justify skipping a crawl."""
        return self.entry_count > 0 and self.lastmod_count > 0

    def to_state(self, *, crawled_at: datetime) -> dict[str, Any]:
        """The jsonb payload persisted on ``websites.sitemap_state``."""
        return {
            "fingerprint": self.fingerprint,
            "entry_count": self.entry_count,
            "lastmod_count": self.lastmod_count,
            "crawled_at": crawled_at.isoformat(),
        }


def state_is_fresh(
    state: dict[str, Any],
    *,
    max_age_hours: int,
    now: Optional[datetime] = None,
) -> bool:
    """True when the state's crawled_at is within the forced-recrawl window.

    A full crawl still runs periodically even when the fingerprint never
    changes, bounding staleness for CMSes whose lastmod is unreliable.
    """
    crawled_at_raw = state.get("crawled_at")
    if not isinstance(crawled_at_raw, str):
        return False
    try:
        crawled_at = datetime.fromisoformat(crawled_at_raw)
    except ValueError:
        return False
    if crawled_at.tzinfo is None:
        crawled_at = crawled_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return now - crawled_at < timedelta(hours=max_age_hours)


def _parse_blocks(
    xml: str, block_pattern: re.Pattern[str]
) -> list[tuple[str, Optional[str]]]:
    """Extract (loc, lastmod) tuples from <url> or <sitemap> blocks.

    Regex parsing on attacker-controlled XML is intentional: only <loc> and
    <lastmod> text is needed, and a parse miss merely fails the probe.
    html.unescape handles entity-encoded locs (e.g. ``&amp;`` in query
    strings) in a single pass.
    """
    entries: list[tuple[str, Optional[str]]] = []
    for block_match in block_pattern.finditer(xml):
        block = block_match.group(0)
        loc_match = _LOC.search(block)
        if not loc_match:
            continue
        lastmod_match = _LASTMOD.search(block)
        entries.append(
            (
                html.unescape(loc_match.group(1)),
                lastmod_match.group(1) if lastmod_match else None,
            )
        )
    return entries


async def _fetch_xml(
    session: aiohttp.ClientSession,
    url: str,
    auth: Optional[aiohttp.BasicAuth],
) -> Optional[str]:
    """Fetch one sitemap document, bounded in size, handling .gz payloads."""
    async with session.get(
        url,
        auth=auth,
        timeout=aiohttp.ClientTimeout(total=_FETCH_TIMEOUT_SECONDS),
        headers={"accept": "application/xml,text/xml,*/*;q=0.5"},
    ) as response:
        if response.status != 200:
            return None
        raw = await response.content.read(_MAX_FETCH_BYTES + 1)
        if len(raw) > _MAX_FETCH_BYTES:
            return None
        # aiohttp transparently decodes content-encoding gzip; a .gz file
        # served as application/gzip arrives still compressed
        if raw[:2] == b"\x1f\x8b":
            decompressor = zlib.decompressobj(wbits=31)
            raw = decompressor.decompress(raw, _MAX_FETCH_BYTES)
            if decompressor.unconsumed_tail:
                return None
        return raw.decode("utf-8", errors="replace")


async def probe_sitemap(
    url: str,
    *,
    http_user: Optional[str] = None,
    http_pass: Optional[str] = None,
) -> Optional[SitemapProbe]:
    """Fingerprint the sitemap at ``url``. None means "could not probe"
    and the caller must proceed with a full crawl."""
    auth = aiohttp.BasicAuth(http_user, http_pass) if http_user and http_pass else None
    try:
        async with asyncio.timeout(_PROBE_BUDGET_SECONDS):
            async with aiohttp.ClientSession() as session:
                xml = await _fetch_xml(session, url, auth)
                if xml is None:
                    return None

                if _IS_INDEX.search(xml):
                    subs = _parse_blocks(xml, _SITEMAP_BLOCK)
                    if not subs or len(subs) > _MAX_SUB_SITEMAPS:
                        return None
                    entries: list[tuple[str, Optional[str]]] = []
                    for sub_url, _ in subs:
                        sub_xml = await _fetch_xml(session, sub_url, auth)
                        # One level of nesting only; an index-of-indexes
                        # fails the probe rather than being half-read
                        if sub_xml is None or _IS_INDEX.search(sub_xml):
                            return None
                        entries.extend(_parse_blocks(sub_xml, _URL_BLOCK))
                else:
                    entries = _parse_blocks(xml, _URL_BLOCK)
    except (aiohttp.ClientError, asyncio.TimeoutError, zlib.error) as exc:
        logger.warning(
            "Sitemap probe failed; proceeding with full crawl",
            extra={"sitemap_url": url, "error": str(exc)},
        )
        return None

    if not entries:
        return None

    lines = sorted(f"{loc}\t{lastmod or ''}" for loc, lastmod in entries)
    fingerprint = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return SitemapProbe(
        fingerprint=fingerprint,
        entry_count=len(entries),
        lastmod_count=sum(1 for _, lastmod in entries if lastmod),
    )
