"""Result types for the admin-tenant website-delete flow.

The Webbplatser admin tab needs the operator to be able to remove a
website from the tenant inventory entirely — distinct from pausing
(setting update_interval=NEVER) or aborting an active crawl. The DELETE
endpoint is tenant-scoped + admin-gated; this module defines the typed
union the router uses to switch on outcome.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID


class CrawlWebsiteDeleteConflictCode(StrEnum):
    """Reason a delete attempt was refused at the repo layer.

    `ACTIVE_JOB_BLOCKING` fires when the website has a queued or
    running crawl job; the operator must abort it first via the
    existing abort flow so the worker doesn't keep trying to write
    crawl_runs against a now-deleted website row.
    """

    ACTIVE_JOB_BLOCKING = "ACTIVE_JOB_BLOCKING"


@dataclass(frozen=True, slots=True)
class CrawlWebsiteDeleteWebsite:
    """Minimal snapshot of the deleted website captured before the row
    disappears, used to populate audit metadata."""

    id: UUID
    url: str
    name: str | None


@dataclass(frozen=True, slots=True)
class CrawlWebsiteDeleteSucceeded:
    website: CrawlWebsiteDeleteWebsite


@dataclass(frozen=True, slots=True)
class CrawlWebsiteDeleteNotFound:
    website_id: UUID


@dataclass(frozen=True, slots=True)
class CrawlWebsiteDeleteBlocked:
    website: CrawlWebsiteDeleteWebsite
    code: CrawlWebsiteDeleteConflictCode


CrawlWebsiteDeleteResult: TypeAlias = (
    CrawlWebsiteDeleteSucceeded | CrawlWebsiteDeleteNotFound | CrawlWebsiteDeleteBlocked
)
