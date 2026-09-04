from unittest.mock import AsyncMock, patch

import pytest

from eneo.worker.crawl.heartbeat import (
    CrawlLeaseLostError,
    HeartbeatFailedError,
    HeartbeatMonitor,
)


async def test_tick_renews_only_after_interval() -> None:
    renew = AsyncMock(return_value=True)
    monitor = HeartbeatMonitor(
        renew_lease=renew,
        interval_seconds=300,
        max_failures=3,
    )
    monitor._last_beat_time = 100.0

    with patch("eneo.worker.crawl.heartbeat.time.time", return_value=350.0):
        await monitor.tick()
    renew.assert_not_awaited()

    with patch("eneo.worker.crawl.heartbeat.time.time", return_value=401.0):
        await monitor.tick()
    renew.assert_awaited_once()


async def test_false_renewal_stops_stale_worker_immediately() -> None:
    monitor = HeartbeatMonitor(
        renew_lease=AsyncMock(return_value=False),
        interval_seconds=1,
        max_failures=3,
    )

    with pytest.raises(CrawlLeaseLostError):
        await monitor.tick()


async def test_transient_database_failure_is_bounded_and_resets() -> None:
    renew = AsyncMock(side_effect=[RuntimeError("database unavailable"), True])
    monitor = HeartbeatMonitor(
        renew_lease=renew,
        interval_seconds=1,
        max_failures=2,
    )

    await monitor._execute_heartbeat()
    assert monitor.consecutive_failures == 1
    await monitor._execute_heartbeat()
    assert monitor.consecutive_failures == 0


async def test_repeated_database_failure_interrupts_worker() -> None:
    monitor = HeartbeatMonitor(
        renew_lease=AsyncMock(side_effect=RuntimeError("database unavailable")),
        interval_seconds=1,
        max_failures=2,
    )

    await monitor._execute_heartbeat()
    with pytest.raises(HeartbeatFailedError) as error:
        await monitor._execute_heartbeat()

    assert error.value.consecutive_failures == 2
    assert error.value.max_failures == 2


@pytest.mark.parametrize(("interval", "failures"), [(0, 1), (1, 0)])
def test_heartbeat_limits_must_be_positive(interval: int, failures: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        HeartbeatMonitor(
            renew_lease=AsyncMock(return_value=True),
            interval_seconds=interval,
            max_failures=failures,
        )
