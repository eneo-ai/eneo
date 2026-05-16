"""Typed result domain for tenant-admin crawl retry-now requests.

A tenant admin operating on the crawler admin page can request an
immediate re-crawl of a website that has failed or been backed off,
without waiting for the scheduler to pick it up at the next interval.
The retry flow is intentionally lighter than the abort/circuit-reset
flows: it does not touch circuit-breaker counters, it does not change
the website's `update_interval`, and it does not write a terminal
event on any prior crawl run. It just queues a fresh crawl via the
existing `CrawlService.crawl(website)` path (which already handles
feeder-vs-direct enqueue depending on the runtime setting).

The discriminated union here keeps the router's response logic typed
and lets the audit emitter route metadata through the standard
`_AuditableWebsite` Protocol used by the other admin-website actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CrawlRetryWebsite:
    """Subset of `Website` exposed to the audit emitter.

    Mirrors `CrawlAbortWebsite` / `CrawlCircuitResetWebsite` /
    `CrawlIntervalChangeWebsite` so the shared `_AuditableWebsite`
    Protocol at `crawler_admin_router.py` accepts every result type
    without a per-type adapter.
    """

    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class CrawlRetryQueued:
    """The retry was accepted; a fresh crawl run was queued.

    `crawl_run_id` is the brand-new run, NOT the prior failed run.
    Operators audit-trail the request with both the website ID and the
    new run ID so a future cross-reference can confirm the retry
    actually executed.
    """

    website: CrawlRetryWebsite
    crawl_run_id: UUID


@dataclass(frozen=True, slots=True)
class CrawlRetryNotFound:
    """No website matched the supplied `website_id` inside the tenant.

    The tenant-scope check is enforced at the repository layer; this
    result hides whether the website exists in another tenant from
    the caller (no cross-tenant existence oracle).
    """

    website_id: UUID


CrawlRetryResult: TypeAlias = CrawlRetryQueued | CrawlRetryNotFound
