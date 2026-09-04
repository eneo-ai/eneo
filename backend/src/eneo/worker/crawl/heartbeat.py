from __future__ import annotations

import time
from collections.abc import Awaitable, Callable


class HeartbeatFailedError(Exception):
    def __init__(self, consecutive_failures: int, max_failures: int):
        self.consecutive_failures = consecutive_failures
        self.max_failures = max_failures
        super().__init__(
            f"Heartbeat failures ({consecutive_failures}) exceeded threshold "
            f"({max_failures})"
        )


class CrawlLeaseLostError(Exception):
    """The current worker no longer owns the persisted crawl attempt."""


class HeartbeatMonitor:
    """Renew one PostgreSQL crawl lease on a bounded interval."""

    def __init__(
        self,
        *,
        renew_lease: Callable[[], Awaitable[bool]],
        interval_seconds: int,
        max_failures: int,
    ) -> None:
        if interval_seconds <= 0 or max_failures <= 0:
            raise ValueError("Heartbeat interval and failure limit must be positive")
        self._renew_lease = renew_lease
        self._interval_seconds = interval_seconds
        self._max_failures = max_failures
        self._last_beat_time = 0.0
        self._consecutive_failures = 0

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    async def tick(self) -> None:
        current_time = time.time()
        if current_time - self._last_beat_time < self._interval_seconds:
            return
        await self._execute_heartbeat()
        self._last_beat_time = current_time

    async def _execute_heartbeat(self) -> None:
        try:
            renewed = await self._renew_lease()
        except Exception as exc:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._max_failures:
                raise HeartbeatFailedError(
                    self._consecutive_failures,
                    self._max_failures,
                ) from exc
            return

        self._consecutive_failures = 0
        if not renewed:
            raise CrawlLeaseLostError("Crawl attempt lease is no longer current")
