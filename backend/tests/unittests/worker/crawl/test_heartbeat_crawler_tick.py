"""Worker-side `HeartbeatMonitor.crawler_tick()` translation seam.

Guards the layer boundary between worker preemption signals and the
crawler-layer terminal stop signal. Without these translations, the
crawler module would either need to import worker exception types
(`JobPreemptedError`, `HeartbeatFailedError`) — breaking layer
separation — or fall back to a broad `except Exception` which is the
defect codex peer review surfaced in tranche 3.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from intric.main.exceptions import CrawlPreempted
from intric.worker.crawl.heartbeat import (
    HeartbeatFailedError,
    HeartbeatMonitor,
    JobPreemptedError,
)


@pytest.mark.asyncio
async def test_crawler_tick_translates_job_preempted_error_to_crawl_preempted() -> None:
    """Admin abort path: worker detects external FAILED -> raises
    `JobPreemptedError` from `_check_preemption`. `crawler_tick` must
    re-raise as `CrawlPreempted` so the crawler's heartbeat helper can
    signal `manager.stop_crawl(reason="preempted")` without importing
    worker types."""
    monitor = HeartbeatMonitor(
        job_id=uuid4(),
        redis_client=None,
        tenant=None,
        interval_seconds=0,
        max_failures=3,
        semaphore_ttl_seconds=600,
    )

    expected_job_id = uuid4()

    async def _raise_job_preempted() -> None:
        raise JobPreemptedError(expected_job_id)

    monitor._execute_heartbeat = _raise_job_preempted  # type: ignore[method-assign]

    with pytest.raises(CrawlPreempted) as exc_info:
        await monitor.crawler_tick()

    assert isinstance(exc_info.value.__cause__, JobPreemptedError)
    assert str(expected_job_id) in exc_info.value.reason


@pytest.mark.asyncio
async def test_crawler_tick_translates_heartbeat_failed_error_to_crawl_preempted() -> (
    None
):
    """Degraded-infrastructure path: consecutive Redis pipeline failures
    cross the threshold -> `HeartbeatFailedError`. Continuing to crawl
    after the slot TTL refresh has failed risks the slot being reclaimed
    by another worker and producing duplicate embedding work, so the
    crawler must terminate. `crawler_tick` translates this terminal
    signal to `CrawlPreempted` with the failure counts carried through
    in the reason string for operator diagnostics."""
    monitor = HeartbeatMonitor(
        job_id=uuid4(),
        redis_client=None,
        tenant=None,
        interval_seconds=0,
        max_failures=3,
        semaphore_ttl_seconds=600,
    )

    async def _raise_heartbeat_failed() -> None:
        raise HeartbeatFailedError(consecutive_failures=3, max_failures=3)

    monitor._execute_heartbeat = _raise_heartbeat_failed  # type: ignore[method-assign]

    with pytest.raises(CrawlPreempted) as exc_info:
        await monitor.crawler_tick()

    assert isinstance(exc_info.value.__cause__, HeartbeatFailedError)
    assert "3/3" in exc_info.value.reason


@pytest.mark.asyncio
async def test_crawler_tick_lets_transient_exceptions_through_untranslated() -> None:
    """Generic transient errors (DB hiccup, Redis blip below threshold)
    must NOT be wrapped as `CrawlPreempted` — the crawler's heartbeat
    helper logs them and continues. Wrapping them would prematurely
    terminate crawls for non-terminal hiccups."""
    monitor = HeartbeatMonitor(
        job_id=uuid4(),
        redis_client=None,
        tenant=None,
        interval_seconds=0,
        max_failures=3,
        semaphore_ttl_seconds=600,
    )

    async def _raise_runtime_error() -> None:
        raise RuntimeError("transient connection blip")

    monitor._execute_heartbeat = _raise_runtime_error  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="transient connection blip"):
        await monitor.crawler_tick()
