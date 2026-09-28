"""Turn destination-policy refusals into quiet, unretried skips.

A refused destination surfaces from Twisted as a DNS lookup failure, which
Scrapy would retry and log with a traceback. When the name resolver guard has
recorded the refusal, this middleware replaces the failure with IgnoreRequest
(no retry, no error log) and counts it, so the crawl result can still treat
it as a download failure rather than proof that a page is gone.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from scrapy.exceptions import IgnoreRequest  # pyright: ignore[reportMissingTypeStubs]
from twisted.internet import reactor
from twisted.internet.error import DNSLookupError

from eneo.crawler.destination_policy import GuardedNameResolver

logger = logging.getLogger(__name__)

REFUSED_STAT = "destination_policy/refused"


class DestinationRefusedMiddleware:
    """Must run before RetryMiddleware on the exception path, i.e. with a
    higher priority number than it (retry is 550 by default)."""

    def __init__(self, stats: Any) -> None:
        self._stats = stats

    @classmethod
    def from_crawler(cls, crawler: Any) -> "DestinationRefusedMiddleware":
        return cls(crawler.stats)

    def process_exception(
        self, request: Any, exception: BaseException, spider: Any = None
    ) -> None:
        # ``spider`` is optional: Scrapy 2.11 passes it, 2.16+ deprecates it.
        if not isinstance(exception, DNSLookupError):
            return None
        url = str(getattr(request, "url", ""))
        host = urlparse(url).hostname
        guard = getattr(reactor, "nameResolver", None)
        if host is None or not isinstance(guard, GuardedNameResolver):
            return None
        refused = guard.refused_addresses(host)
        if refused is None:
            return None
        logger.warning(
            "Skipping %s: destination %s (%s) refused by crawler policy",
            url,
            host,
            ", ".join(refused),
        )
        self._stats.inc_value(REFUSED_STAT, spider=spider)
        raise IgnoreRequest(f"Destination refused by crawler policy: {host}")
