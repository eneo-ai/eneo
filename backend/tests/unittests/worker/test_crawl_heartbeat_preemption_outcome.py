"""Heartbeat-driven preemption maps to `CRAWL_HEARTBEAT_FAILED`.

The crawler module's heartbeat translator raises `CrawlPreempted` for
two distinct sources: an admin clicking Cancel (the worker observed
`Jobs.status=FAILED` via DB poll) and the heartbeat monitor exceeding
its `crawl_heartbeat_max_failures` threshold (Redis/DB liveness writes
keep failing). Operators reading the admin recent-failures view used
to see both cases land on the generic `UNKNOWN_CRAWL_ERROR` outcome —
making "the heartbeat broke" indistinguishable from any other bug.

This tranche introduces `CrawlPreemptionCause` to discriminate the two
sources at raise time, and branches `_crawl_task_exception_outcome` so
heartbeat-failure preemptions land on the new typed
`CrawlOutcomeCode.CRAWL_HEARTBEAT_FAILED` outcome.

These unit tests pin both ends of that contract: the raise-time
discriminator + the outcome-mapping branch.
"""

from __future__ import annotations

import pytest

from intric.crawler.crawler import CrawlShutdownError
from intric.main.exceptions import (
    CrawlPreempted,
    CrawlPreemptionCause,
)
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.worker.crawl.heartbeat import (
    HeartbeatFailedError,
    JobPreemptedError,
)
from intric.worker.crawl_tasks import (
    CrawlMaxAgeExceededError,
    _crawl_task_exception_outcome,
)


def test_crawl_preempted_default_cause_is_admin_abort() -> None:
    """Backward-compatibility: callers that raise `CrawlPreempted(reason)`
    without specifying `cause` get the admin-abort discriminator. Admin
    abort already commits a typed `CRAWL_ABORTED` terminal event via the
    abort flow, so this branch lets the worker exit cleanly without a
    second outcome write."""
    exc = CrawlPreempted("test reason")

    assert exc.reason == "test reason"
    assert exc.cause == CrawlPreemptionCause.ADMIN_ABORT


def test_crawl_preempted_accepts_explicit_heartbeat_cause() -> None:
    exc = CrawlPreempted(
        "heartbeat exceeded", cause=CrawlPreemptionCause.HEARTBEAT_FAILURE
    )

    assert exc.cause == CrawlPreemptionCause.HEARTBEAT_FAILURE
    assert exc.reason == "heartbeat exceeded"


@pytest.mark.asyncio
async def test_heartbeat_failed_error_translates_to_heartbeat_failure_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`HeartbeatMonitor.crawler_tick` re-raises `HeartbeatFailedError`
    as `CrawlPreempted(cause=HEARTBEAT_FAILURE)` so the downstream
    outcome branch can route it to `CRAWL_HEARTBEAT_FAILED`. The tick
    raise site is the only source of `HEARTBEAT_FAILURE` in production;
    pinning the translation here keeps a future refactor from
    accidentally collapsing the two causes into one."""
    from intric.worker.crawl.heartbeat import HeartbeatMonitor

    class _Fake(HeartbeatMonitor):
        def __init__(self) -> None:  # type: ignore[override]
            pass

    fake = _Fake()

    async def boom() -> None:
        raise HeartbeatFailedError(consecutive_failures=5, max_failures=3)

    monkeypatch.setattr(fake, "tick", boom)

    with pytest.raises(CrawlPreempted) as exc_info:
        await fake.crawler_tick()

    assert exc_info.value.cause == CrawlPreemptionCause.HEARTBEAT_FAILURE
    assert "heartbeat failures exceeded threshold" in exc_info.value.reason


@pytest.mark.asyncio
async def test_job_preempted_error_translates_to_admin_abort_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The admin-abort source is the worker observing `Jobs.status=FAILED`
    via the heartbeat DB poll. The abort flow commits `CRAWL_ABORTED`
    independently; the cause on the resulting `CrawlPreempted` is
    informational so the outcome branch falls through to `UNKNOWN`
    rather than writing a second terminal event."""
    from uuid import uuid4

    from intric.worker.crawl.heartbeat import HeartbeatMonitor

    class _Fake(HeartbeatMonitor):
        def __init__(self) -> None:  # type: ignore[override]
            pass

    fake = _Fake()
    job_id = uuid4()

    async def boom() -> None:
        raise JobPreemptedError(job_id=job_id)

    monkeypatch.setattr(fake, "tick", boom)

    with pytest.raises(CrawlPreempted) as exc_info:
        await fake.crawler_tick()

    assert exc_info.value.cause == CrawlPreemptionCause.ADMIN_ABORT
    assert str(job_id) in exc_info.value.reason


def test_exception_outcome_maps_heartbeat_preempted_to_heartbeat_failed() -> None:
    """The new typed outcome `CRAWL_HEARTBEAT_FAILED` is the discriminator
    operators see in the admin recent-failures view. Without this branch
    the worker's outer exception handler would write
    `UNKNOWN_CRAWL_ERROR`, hiding heartbeat-driven terminations behind
    the generic bug-catch bucket."""
    exc = CrawlPreempted(
        "heartbeat failures exceeded threshold (5/3)",
        cause=CrawlPreemptionCause.HEARTBEAT_FAILURE,
    )

    assert _crawl_task_exception_outcome(exc) == CrawlOutcomeCode.CRAWL_HEARTBEAT_FAILED


def test_exception_outcome_maps_admin_abort_preempted_to_unknown_fallback() -> None:
    """Admin-abort preemptions fall through to `UNKNOWN_CRAWL_ERROR` on
    purpose: the abort flow already wrote `CRAWL_ABORTED`, and the
    outer exception handler should not race a second terminal commit
    on the same job. Pinning this branch here makes the "admin abort
    does NOT trigger a heartbeat-failure outcome" guarantee testable."""
    exc = CrawlPreempted(
        "job preempted (external FAILED state)",
        cause=CrawlPreemptionCause.ADMIN_ABORT,
    )

    assert _crawl_task_exception_outcome(exc) == CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR


def test_exception_outcome_preserves_pre_existing_branches() -> None:
    """Regression guard: the heartbeat branch must not shadow the
    existing `CrawlShutdownError` / `CrawlMaxAgeExceededError` cases.
    Each of those failure modes carries a distinct typed outcome and
    operators rely on the discrimination in alerts."""
    assert (
        _crawl_task_exception_outcome(
            CrawlShutdownError(url="https://test.example.com", shutdown_timeout=10.0)
        )
        == CrawlOutcomeCode.CRAWL_SHUTDOWN_ERROR
    )
    assert (
        _crawl_task_exception_outcome(CrawlMaxAgeExceededError("test"))
        == CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED
    )
    assert (
        _crawl_task_exception_outcome(RuntimeError("unrelated"))
        == CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR
    )
