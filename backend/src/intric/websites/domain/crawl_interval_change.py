from dataclasses import dataclass
from typing import TypeAlias
from uuid import UUID

from intric.websites.domain.website import UpdateInterval


@dataclass(frozen=True, slots=True)
class CrawlIntervalChangeWebsite:
    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class CrawlIntervalChangeApplied:
    """The interval was different and has been written. Audit row is required.

    `failure_state_cleared` is True when the change resumed an auto-disabled
    website (previous=NEVER + counters ≥ threshold + new=recurring) and the
    repo therefore also cleared `consecutive_failures` and `next_retry_at`.
    Without that side effect the next failure would immediately re-trip the
    auto-disable, leaving operators with no recovery path short of calling
    the dedicated `/reset-circuit-breaker` endpoint as well.
    """

    website: CrawlIntervalChangeWebsite
    previous_update_interval: UpdateInterval
    new_update_interval: UpdateInterval
    failure_state_cleared: bool = False
    previous_consecutive_failures: int = 0


@dataclass(frozen=True, slots=True)
class CrawlIntervalChangeUnchanged:
    """Idempotent no-op. The website already had the requested interval; no audit row written."""

    website: CrawlIntervalChangeWebsite
    update_interval: UpdateInterval


@dataclass(frozen=True, slots=True)
class CrawlIntervalChangeNotFound:
    website_id: UUID


CrawlIntervalChangeResult: TypeAlias = (
    CrawlIntervalChangeApplied
    | CrawlIntervalChangeUnchanged
    | CrawlIntervalChangeNotFound
)
