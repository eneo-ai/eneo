"""Result types for tenant-admin bulk crawl interval changes.

Bulk changes intentionally reuse the single-website interval setter
instead of issuing one SQL UPDATE. That setter owns the auto-disabled
resume invariant: switching from NEVER to a recurring interval clears
`consecutive_failures` and `next_retry_at` only when the website was
paused by the failure threshold. Keeping that rule in one place avoids
parallel counter-reset behavior.

Applied rows are audited per website, not as one batch event, so the
audit trail keeps `EntityType.WEBSITE` as its searchable primary
entity and preserves the same metadata shape as the single-row action.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID

from intric.websites.domain.website import UpdateInterval


class BulkIntervalRowFailureCode(StrEnum):
    """Reason a bulk-interval row didn't apply.

    `NOT_FOUND` is what the underlying setter returns when the
    `(website_id, tenant_id)` pair has no match, covering both
    "deleted concurrently" and "cross-tenant id guess".
    """

    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class BulkIntervalRowApplied:
    website_id: UUID
    website_name: str
    previous_update_interval: UpdateInterval
    new_update_interval: UpdateInterval
    failure_state_cleared: bool
    # Audit rows need the pre-write counter value to explain why a
    # schedule change also cleared failure state.
    previous_consecutive_failures: int


@dataclass(frozen=True, slots=True)
class BulkIntervalRowUnchanged:
    website_id: UUID
    website_name: str
    update_interval: UpdateInterval


@dataclass(frozen=True, slots=True)
class BulkIntervalRowFailed:
    website_id: UUID
    code: BulkIntervalRowFailureCode


BulkIntervalRowResult: TypeAlias = (
    BulkIntervalRowApplied | BulkIntervalRowUnchanged | BulkIntervalRowFailed
)


@dataclass(frozen=True, slots=True)
class BulkIntervalChangeResult:
    """Aggregated outcome of the bulk-interval batch."""

    applied: tuple[BulkIntervalRowApplied, ...]
    unchanged: tuple[BulkIntervalRowUnchanged, ...]
    failed: tuple[BulkIntervalRowFailed, ...]


# Keep explicit-ID batches bounded until "select all matching filter"
# can run and audit the filtered set in the same transaction.
BULK_INTERVAL_MAX_WEBSITE_IDS = 100
