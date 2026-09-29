from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from eneo.websites.domain.crawl_schedule import (
    SCHEDULER_STALE_AFTER,
    SchedulerRunRecord,
    SchedulerTenantCounts,
    ScheduleState,
    ceil_to_tick,
    compute_schedule,
    next_weekly_slot,
    scheduler_health_status,
)
from eneo.websites.domain.website import UpdateInterval

UTC = timezone.utc
# 2026-09-21 is a Monday.
WED = datetime(2026, 9, 23, 10, 30, tzinfo=UTC)
THU = datetime(2026, 9, 24, 10, 30, tzinfo=UTC)
FRI = datetime(2026, 9, 25, 10, 30, tzinfo=UTC)
SAT = datetime(2026, 9, 26, 10, 30, tzinfo=UTC)
NEXT_FRI = datetime(2026, 10, 2, 0, 0, tzinfo=UTC)
LONG_AGO = datetime(2026, 9, 1, 8, 15, tzinfo=UTC)


def _at(day: datetime, hour: int, minute: int = 0, **rest: int) -> datetime:
    fields = {"hour": hour, "minute": minute, "second": 0, "microsecond": 0}
    fields.update(rest)
    return day.replace(**fields)


# --- scheduler health -------------------------------------------------------


def _record(ran_at: datetime, *, tenant_failed: int, tenant_id) -> SchedulerRunRecord:
    return SchedulerRunRecord(
        ran_at=ran_at,
        due=3,
        admitted=3 - tenant_failed,
        failed=tenant_failed,
        tenants={tenant_id: SchedulerTenantCounts(3, 3 - tenant_failed, tenant_failed)},
    )


def test_missing_marker_is_stale() -> None:
    assert scheduler_health_status(None, tenant_id=uuid4(), now=WED) == "stale"


@pytest.mark.parametrize(
    ("age", "failed", "expected"),
    [
        (timedelta(minutes=5), 0, "ok"),
        (timedelta(minutes=5), 1, "degraded"),
        (SCHEDULER_STALE_AFTER, 0, "ok"),
        (SCHEDULER_STALE_AFTER + timedelta(seconds=1), 0, "stale"),
        (timedelta(minutes=66), 4, "stale"),
        (timedelta(minutes=-5), 0, "ok"),
    ],
)
def test_health_status_is_judged_by_age_then_failures(
    age: timedelta, failed: int, expected: str
) -> None:
    tenant_id = uuid4()
    record = _record(WED - age, tenant_failed=failed, tenant_id=tenant_id)

    assert scheduler_health_status(record, tenant_id=tenant_id, now=WED) == expected


def test_health_status_only_sees_the_callers_tenant() -> None:
    other = uuid4()
    record = _record(WED, tenant_failed=2, tenant_id=other)

    assert scheduler_health_status(record, tenant_id=uuid4(), now=WED) == "ok"
    assert record.for_tenant(uuid4()) == SchedulerTenantCounts()


# --- tick helpers -----------------------------------------------------------


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (_at(WED, 10), _at(WED, 10)),
        (_at(WED, 10, microsecond=1), _at(WED, 11)),
        (_at(WED, 10, 30), _at(WED, 11)),
        (_at(WED, 23, 30), _at(THU, 0)),
    ],
)
def test_ceil_to_tick(moment: datetime, expected: datetime) -> None:
    assert ceil_to_tick(moment) == expected


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (FRI, FRI),
        (_at(FRI, 23, 59), _at(FRI, 23, 59)),
        (_at(SAT, 0), NEXT_FRI),
        (_at(THU, 23, 59), _at(FRI, 0)),
        (WED, _at(FRI, 0)),
        # 01:30 on Friday in UTC+2 is still Thursday evening in UTC.
        (
            datetime(2026, 9, 25, 1, 30, tzinfo=timezone(timedelta(hours=2))),
            _at(FRI, 0),
        ),
    ],
)
def test_next_weekly_slot(moment: datetime, expected: datetime) -> None:
    assert next_weekly_slot(moment) == expected


# --- compute_schedule -------------------------------------------------------

DAILY = UpdateInterval.DAILY
WEEKLY = UpdateInterval.WEEKLY
NEVER = UpdateInterval.NEVER

# (id, interval, interval_due_at, next_retry_at, active, failures, now,
#  state, next_due_at, blocked_until)
CASES = [
    ("never", NEVER, None, None, False, 0, WED, "disabled", None, None),
    ("never-9", NEVER, None, None, False, 9, WED, "disabled", None, None),
    ("never-10", NEVER, None, None, False, 10, WED, "disabled", None, None),
    (
        "never-beats-blockers",
        NEVER,
        LONG_AGO,
        _at(WED, 12),
        True,
        0,
        WED,
        "disabled",
        None,
        None,
    ),
    (
        "never-crawled-daily",
        DAILY,
        LONG_AGO,
        None,
        False,
        0,
        WED,
        "due",
        _at(WED, 11),
        None,
    ),
    (
        "due-long-ago",
        DAILY,
        _at(WED, 7, 30),
        None,
        False,
        0,
        WED,
        "due",
        _at(WED, 11),
        None,
    ),
    (
        "now-on-tick",
        DAILY,
        _at(WED, 7, 30),
        None,
        False,
        0,
        _at(WED, 10),
        "due",
        _at(WED, 10),
        None,
    ),
    (
        "waiting",
        DAILY,
        _at(WED, 10, 40),
        None,
        False,
        0,
        WED,
        "waiting",
        _at(WED, 11),
        None,
    ),
    (
        "waiting-on-hour",
        DAILY,
        _at(WED, 11),
        None,
        False,
        0,
        WED,
        "waiting",
        _at(WED, 11),
        None,
    ),
    (
        "waiting-past-hour",
        DAILY,
        _at(WED, 11, microsecond=1),
        None,
        False,
        0,
        WED,
        "waiting",
        _at(WED, 12),
        None,
    ),
    (
        "backoff",
        DAILY,
        _at(WED, 7, 30),
        _at(WED, 12),
        False,
        3,
        WED,
        "blocked_backoff",
        _at(WED, 12),
        _at(WED, 12),
    ),
    (
        "backoff-off-hour",
        DAILY,
        _at(WED, 7, 30),
        _at(WED, 12, second=1),
        False,
        3,
        WED,
        "blocked_backoff",
        _at(WED, 13),
        _at(WED, 12, second=1),
    ),
    (
        "backoff-expired",
        DAILY,
        _at(WED, 7, 30),
        _at(WED, 9),
        False,
        3,
        WED,
        "due",
        _at(WED, 11),
        None,
    ),
    (
        "waiting-retry-before-interval",
        DAILY,
        _at(WED, 12, 30),
        _at(WED, 11),
        False,
        1,
        WED,
        "waiting",
        _at(WED, 13),
        None,
    ),
    (
        "waiting-retry-after-interval",
        DAILY,
        _at(WED, 10, 40),
        _at(WED, 14),
        False,
        1,
        WED,
        "waiting",
        _at(WED, 14),
        None,
    ),
    (
        "active-elapsed",
        DAILY,
        _at(WED, 7, 30),
        None,
        True,
        0,
        WED,
        "blocked_active_run",
        None,
        None,
    ),
    (
        "active-not-elapsed",
        DAILY,
        _at(WED, 10, 40),
        None,
        True,
        0,
        WED,
        "waiting",
        _at(WED, 11),
        None,
    ),
    (
        "weekly-midweek",
        WEEKLY,
        LONG_AGO,
        None,
        False,
        0,
        WED,
        "waiting",
        _at(FRI, 0),
        None,
    ),
    ("weekly-friday", WEEKLY, LONG_AGO, None, False, 0, FRI, "due", _at(FRI, 11), None),
    (
        "weekly-friday-late",
        WEEKLY,
        _at(FRI, 23, 45),
        None,
        False,
        0,
        _at(FRI, 23, 30),
        "waiting",
        NEXT_FRI,
        None,
    ),
    (
        "weekly-thursday-late",
        WEEKLY,
        _at(THU, 23, 30),
        None,
        False,
        0,
        _at(THU, 23, 30),
        "waiting",
        _at(FRI, 0),
        None,
    ),
    (
        "weekly-backoff-into-saturday",
        WEEKLY,
        LONG_AGO,
        _at(SAT, 8),
        False,
        2,
        FRI,
        "blocked_backoff",
        NEXT_FRI,
        _at(SAT, 8),
    ),
]


@pytest.mark.parametrize(
    (
        "interval",
        "interval_due_at",
        "next_retry_at",
        "active",
        "failures",
        "now",
        "state",
        "next_due_at",
        "blocked_until",
    ),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_compute_schedule(
    interval: UpdateInterval,
    interval_due_at: datetime | None,
    next_retry_at: datetime | None,
    active: bool,
    failures: int,
    now: datetime,
    state: str,
    next_due_at: datetime | None,
    blocked_until: datetime | None,
) -> None:
    projection = compute_schedule(
        update_interval=interval,
        interval_due_at=interval_due_at,
        next_retry_at=next_retry_at,
        has_active_run=active,
        consecutive_failures=failures,
        now=now,
    )

    assert projection.schedule_state == ScheduleState(state)
    assert projection.next_due_at == next_due_at
    assert projection.blocked_until == blocked_until
    assert projection.auto_disabled is (interval is NEVER and failures >= 10)
    if interval is NEVER:
        assert projection.interval_due_at is None
    else:
        assert projection.interval_due_at == interval_due_at
    # A pickup time is always a whole scheduler tick, never in the past.
    if projection.next_due_at is not None:
        assert projection.next_due_at >= now
        assert (
            projection.next_due_at.minute,
            projection.next_due_at.second,
            projection.next_due_at.microsecond,
        ) == (0, 0, 0)
    if interval is WEEKLY and projection.next_due_at is not None:
        assert projection.next_due_at.astimezone(UTC).weekday() == 4


@pytest.mark.parametrize("field", ["now", "interval_due_at", "next_retry_at"])
def test_compute_schedule_rejects_naive_datetimes(field: str) -> None:
    kwargs: dict[str, object] = {
        "update_interval": DAILY,
        "interval_due_at": LONG_AGO,
        "next_retry_at": None,
        "has_active_run": False,
        "consecutive_failures": 0,
        "now": WED,
    }
    kwargs[field] = datetime(2026, 9, 23, 10, 30)

    with pytest.raises(ValueError, match=field):
        compute_schedule(**kwargs)  # type: ignore[arg-type]
