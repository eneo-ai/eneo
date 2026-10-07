"""Pure crawl-scheduling rules.

Shared by the hourly scheduler query, the admin schedule listing and the
scheduler health marker, so every reader agrees on when a website is due.
Nothing here touches SQL, Redis or the clock: callers pass ``now``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Literal
from uuid import UUID

from eneo.websites.domain.website import UpdateInterval

SCHEDULE_INTERVALS: Mapping[UpdateInterval, timedelta] = MappingProxyType(
    {
        UpdateInterval.DAILY: timedelta(days=1),
        UpdateInterval.EVERY_OTHER_DAY: timedelta(days=2),
        UpdateInterval.WEEKLY: timedelta(days=7),
    }
)
"""Minimum time between crawls per interval. NEVER is absent on purpose."""

WEEKLY_CRAWL_WEEKDAY = 4
"""Weekly websites are only picked up on Fridays, judged on the UTC date."""

AUTO_DISABLE_FAILURE_THRESHOLD = 10
"""Consecutive failures at which the circuit breaker sets the interval to NEVER."""

SCHEDULER_TICK = timedelta(hours=1)
"""The scheduler cron runs at minute :00 of every hour."""

SCHEDULER_STALE_AFTER = timedelta(minutes=65)
"""A marker older than this means the hourly cron missed at least one tick."""


class ScheduleState(StrEnum):
    DUE = "due"
    WAITING = "waiting"
    BLOCKED_ACTIVE_RUN = "blocked_active_run"
    BLOCKED_BACKOFF = "blocked_backoff"
    DISABLED = "disabled"


SchedulerHealthStatus = Literal["ok", "degraded", "stale", "unknown"]


@dataclass(frozen=True, slots=True)
class SchedulerTenantCounts:
    due: int = 0
    admitted: int = 0
    failed: int = 0


@dataclass(frozen=True, slots=True)
class SchedulerRunRecord:
    """What one scheduler run did, overall and per tenant."""

    ran_at: datetime
    due: int
    admitted: int
    failed: int
    tenants: Mapping[UUID, SchedulerTenantCounts] = field(
        default_factory=dict[UUID, SchedulerTenantCounts]
    )

    def for_tenant(self, tenant_id: UUID) -> SchedulerTenantCounts:
        return self.tenants.get(tenant_id, SchedulerTenantCounts())


def scheduler_health_status(
    record: SchedulerRunRecord | None, *, tenant_id: UUID, now: datetime
) -> SchedulerHealthStatus:
    """Judge the scheduler from its last run, as seen by one tenant.

    ``stale`` wins over ``degraded``: a run that is too old says nothing about
    the present, whatever its counts were.
    """
    if record is None:
        return "stale"
    if now - record.ran_at > SCHEDULER_STALE_AFTER:
        return "stale"
    if record.for_tenant(tenant_id).failed > 0:
        return "degraded"
    return "ok"


@dataclass(frozen=True, slots=True)
class ScheduleProjection:
    interval_due_at: datetime | None
    """When the interval since the last crawl elapses; None when disabled."""

    next_due_at: datetime | None
    """Earliest scheduler tick that can pick the website up; None when
    disabled, or while an active run must finish first."""

    schedule_state: ScheduleState
    blocked_until: datetime | None
    """The circuit-breaker deadline while in BLOCKED_BACKOFF."""

    auto_disabled: bool
    """Interval is NEVER because the circuit breaker switched it off."""


def _require_aware(name: str, moment: datetime | None) -> None:
    if moment is not None and moment.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


def ceil_to_tick(moment: datetime) -> datetime:
    """Round up to the scheduler tick at or after ``moment``."""
    floored = moment.replace(minute=0, second=0, microsecond=0)
    return floored if floored == moment else floored + SCHEDULER_TICK


def next_weekly_slot(moment: datetime) -> datetime:
    """First instant at or after ``moment`` whose UTC date is a Friday.

    Fridays keep ``moment``; other days move to the next Friday 00:00 UTC.
    """
    in_utc = moment.astimezone(timezone.utc)
    days_ahead = (WEEKLY_CRAWL_WEEKDAY - in_utc.weekday()) % 7
    if days_ahead == 0:
        return moment
    friday = in_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    return friday + timedelta(days=days_ahead)


def compute_schedule(
    *,
    update_interval: UpdateInterval,
    interval_due_at: datetime | None,
    next_retry_at: datetime | None,
    has_active_run: bool,
    consecutive_failures: int,
    now: datetime,
) -> ScheduleProjection:
    """Project a website's scheduling state at ``now``.

    Mirrors the scheduler query: a website is picked up once its interval has
    elapsed (weekly ones only on Fridays UTC), no crawl run is active, and any
    circuit-breaker backoff has passed. Precedence when several apply:
    disabled > waiting > blocked by active run > blocked by backoff > due.
    """
    _require_aware("now", now)
    _require_aware("interval_due_at", interval_due_at)
    _require_aware("next_retry_at", next_retry_at)

    if update_interval is UpdateInterval.NEVER or interval_due_at is None:
        return ScheduleProjection(
            interval_due_at=None,
            next_due_at=None,
            schedule_state=ScheduleState.DISABLED,
            blocked_until=None,
            auto_disabled=consecutive_failures >= AUTO_DISABLE_FAILURE_THRESHOLD,
        )

    weekly = update_interval is UpdateInterval.WEEKLY
    friday_now = now.astimezone(timezone.utc).weekday() == WEEKLY_CRAWL_WEEKDAY
    elapsed = interval_due_at <= now and (not weekly or friday_now)

    if not elapsed:
        state = ScheduleState.WAITING
    elif has_active_run:
        state = ScheduleState.BLOCKED_ACTIVE_RUN
    elif next_retry_at is not None and next_retry_at > now:
        state = ScheduleState.BLOCKED_BACKOFF
    else:
        state = ScheduleState.DUE

    if state is ScheduleState.BLOCKED_ACTIVE_RUN:
        next_due_at = None
    else:
        earliest = max(interval_due_at, next_retry_at or interval_due_at, now)
        next_due_at = ceil_to_tick(earliest)
        if weekly:
            next_due_at = next_weekly_slot(next_due_at)

    return ScheduleProjection(
        interval_due_at=interval_due_at,
        next_due_at=next_due_at,
        schedule_state=state,
        blocked_until=next_retry_at if state is ScheduleState.BLOCKED_BACKOFF else None,
        auto_disabled=False,
    )
