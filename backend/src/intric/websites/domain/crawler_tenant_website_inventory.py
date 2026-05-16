"""Domain types for the tenant-wide website governance inventory.

The Crawler Webbplatser admin tab needs a single tenant-scoped view of
every website the tenant has registered — not just the ones currently
running (active inventory) or broken (failure inventory) or active in the
last week (website-processing aggregate). This module defines the
read-side dataclasses for that listing.

`CrawlerTenantWebsiteInventoryItem` is intentionally redundant with parts
of `CrawlerFailureInventoryItem` rather than reusing it; the inventory
view carries ownership/space attribution that the failure view doesn't,
and forcing the failure shape to be a superset would couple two
admin-page surfaces that may otherwise evolve at different cadences.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.crawler_failure_inventory import CrawlerFailureState
from intric.websites.domain.website import UpdateInterval


class CrawlerTenantWebsiteInventorySort(str, Enum):
    """Stable sort orders the admin UI can request.

    Each value matches a deterministic SQL ORDER BY in the repository so a
    page-2 fetch always lands on the rows the operator expects.
    """

    RECENT_CRAWL = "recent_crawl"
    SIZE_DESC = "size_desc"
    CONSECUTIVE_FAILURES = "consecutive_failures"
    URL = "url"


@dataclass(frozen=True, slots=True)
class CrawlerTenantWebsiteInventoryItem:
    """One website row in the governance inventory.

    `failure_state` is `None` for healthy websites; the SQL CASE in the
    repository maps the same AUTO_DISABLED / BACKED_OFF heuristics the
    failure inventory already uses, so a website that shows up in /health
    will carry the matching label here.

    `owner_user_id` + `owner_email` describe the website's *creator* — the
    user who registered the website. This is NOT the user who started the
    most recent crawl (that distinction belongs to the active inventory).
    """

    website_id: UUID
    url: str
    name: str | None
    created_at: datetime
    update_interval: UpdateInterval
    crawl_type: CrawlType
    download_files: bool
    # Whether HTTP Basic Auth credentials are stored for this website.
    # The presence flag is enough for the admin governance surface —
    # the encrypted password itself is never exposed; the username is
    # admin-readable so the admin can verify which account the worker
    # crawls as without round-tripping to the space owner.
    requires_http_auth: bool
    http_auth_username: str | None
    failure_state: CrawlerFailureState | None
    consecutive_failures: int
    next_retry_at: datetime | None
    last_crawled_at: datetime | None
    size_bytes: int
    owner_user_id: UUID | None
    owner_email: str | None
    space_id: UUID | None
    space_name: str | None
    collection_id: UUID | None
    collection_name: str | None


@dataclass(frozen=True, slots=True)
class CrawlerTenantWebsiteInventory:
    items: tuple[CrawlerTenantWebsiteInventoryItem, ...]
    total: int
    limit: int
    offset: int
