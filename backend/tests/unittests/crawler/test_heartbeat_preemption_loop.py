"""Heartbeat preemption loop: bounded-latency stop on admin abort.

When the heartbeat callback raises `CrawlPreempted`, the crawler must
(1) stop the Scrapy engine via `manager.stop_crawl(reason=...)` within
one heartbeat interval, and (2) propagate the preemption exception rather
than swallowing it.

The broad `except Exception` swallow that previously lived at
`crawler.py:741` and `:856` ate this signal and let the worker keep
embedding/persisting until the next heartbeat or the configured
`max_length` timeout — bypassing the safe-cleanup-skip guarantee of
admin-initiated aborts.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from intric.crawler.crawler import _run_heartbeat_until_done
from intric.main.exceptions import CrawlPreempted


class _FakeCrawlManager:
    """Records stop_crawl calls for latency / wiring assertions."""

    def __init__(self) -> None:
        self.stop_calls: list[tuple[float, str]] = []

    def stop_crawl(self, *, reason: str) -> None:
        self.stop_calls.append((time.monotonic(), reason))


@pytest.mark.asyncio
async def test_heartbeat_loop_returns_none_when_crawl_finishes_cleanly() -> None:
    """If the crawl signals done before any heartbeat tick, the helper exits
    without calling stop_crawl and returns None — preserving the normal
    completion path."""
    manager = _FakeCrawlManager()
    crawl_done = asyncio.Event()
    crawl_done.set()

    async def heartbeat_callback() -> None:
        raise AssertionError("heartbeat must not run when crawl is already done")

    result = await _run_heartbeat_until_done(
        manager=manager,
        crawl_done=crawl_done,
        heartbeat_callback=heartbeat_callback,
        heartbeat_interval=60.0,
        preempt_shutdown_reason="preempted",
    )

    assert result is None
    assert manager.stop_calls == []


@pytest.mark.asyncio
async def test_heartbeat_loop_swallows_transient_callback_error_and_continues() -> None:
    """A non-preemption exception from the heartbeat callback (transient DB
    failure, Redis blip) is logged and the loop continues — the broader
    `except Exception` swallow was correct for these errors, only wrong for
    terminal preemption signals."""
    manager = _FakeCrawlManager()
    crawl_done = asyncio.Event()
    call_count = 0

    async def heartbeat_callback() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient DB heartbeat error")

    async def signal_done_after_two_ticks() -> None:
        await asyncio.sleep(0.06)
        crawl_done.set()

    signal_task = asyncio.create_task(signal_done_after_two_ticks())
    try:
        result = await _run_heartbeat_until_done(
            manager=manager,
            crawl_done=crawl_done,
            heartbeat_callback=heartbeat_callback,
            heartbeat_interval=0.02,
            preempt_shutdown_reason="preempted",
        )
    finally:
        signal_task.cancel()
        try:
            await signal_task
        except asyncio.CancelledError:
            pass

    assert result is None
    assert manager.stop_calls == []
    # Loop must have made at least two heartbeat attempts (one that raised,
    # at least one that succeeded) before crawl_done fired.
    assert call_count >= 2


@pytest.mark.asyncio
async def test_heartbeat_loop_propagates_preemption_and_signals_stop_crawl() -> None:
    """Preemption signal must (a) call `manager.stop_crawl(reason=...)` and
    (b) return the `CrawlPreempted` exception so the caller can raise it
    after the blocking crawl thread observes the engine shutdown."""
    manager = _FakeCrawlManager()
    crawl_done = asyncio.Event()
    preempt_signal = CrawlPreempted("admin abort")

    async def heartbeat_callback() -> None:
        raise preempt_signal

    result = await _run_heartbeat_until_done(
        manager=manager,
        crawl_done=crawl_done,
        heartbeat_callback=heartbeat_callback,
        heartbeat_interval=60.0,
        preempt_shutdown_reason="preempted",
    )

    assert result is preempt_signal
    assert len(manager.stop_calls) == 1
    assert manager.stop_calls[0][1] == "preempted"


@pytest.mark.asyncio
async def test_heartbeat_task_is_cancellable_when_callback_is_stuck() -> None:
    """The crawler timeout wrapper must cancel heartbeat teardown promptly.

    The outer `_run_crawl_with_timeout` / `_run_sitemap_crawl_with_timeout`
    pattern wraps the heartbeat helper in an `asyncio.Task`. If the callback
    is stuck mid-await on a degraded dependency (slow Redis, stalled DB
    connection), teardown must cancel the task instead of waiting for the
    client's own connection timeout.
    """
    manager = _FakeCrawlManager()
    crawl_done = asyncio.Event()
    callback_started = asyncio.Event()
    callback_release = asyncio.Event()

    async def stuck_callback() -> None:
        callback_started.set()
        await callback_release.wait()  # hangs until released or cancelled

    task = asyncio.create_task(
        _run_heartbeat_until_done(
            manager=manager,
            crawl_done=crawl_done,
            heartbeat_callback=stuck_callback,
            heartbeat_interval=60.0,
            preempt_shutdown_reason="preempted",
        )
    )

    await asyncio.wait_for(callback_started.wait(), timeout=1.0)
    crawl_done.set()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1.0)

    assert manager.stop_calls == []


@pytest.mark.asyncio
async def test_heartbeat_loop_bounded_preemption_latency() -> None:
    """Codex bounded-latency invariant: from the moment the heartbeat raises
    `CrawlPreempted`, `manager.stop_crawl(...)` must be called within one
    heartbeat interval (no second-interval wait). The previous broad
    `except Exception` swallow caused the loop to log and keep ticking,
    pushing the actual stop signal out by `max_length` seconds."""
    manager = _FakeCrawlManager()
    crawl_done = asyncio.Event()
    heartbeat_interval = 0.05

    call_count = 0
    preemption_raised_at: list[float] = []

    async def heartbeat_callback() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None  # first tick is healthy
        preemption_raised_at.append(time.monotonic())
        raise CrawlPreempted("admin abort")

    start = time.monotonic()
    result = await _run_heartbeat_until_done(
        manager=manager,
        crawl_done=crawl_done,
        heartbeat_callback=heartbeat_callback,
        heartbeat_interval=heartbeat_interval,
        preempt_shutdown_reason="preempted",
    )
    elapsed_total = time.monotonic() - start

    assert isinstance(result, CrawlPreempted)
    assert len(manager.stop_calls) == 1

    stop_time = manager.stop_calls[0][0]
    raised_time = preemption_raised_at[0]
    stop_latency = stop_time - raised_time

    # Stop must be called effectively immediately after the callback raises;
    # the loop must not wait another heartbeat interval before signalling.
    assert stop_latency < heartbeat_interval, (
        f"stop_crawl latency {stop_latency:.3f}s exceeded one heartbeat "
        f"interval {heartbeat_interval}s — preemption is being deferred"
    )
    # Total runtime must be bounded by ~2 heartbeat intervals (first tick +
    # second tick). A regression that re-introduces the broad swallow would
    # take O(max_length) seconds here.
    assert elapsed_total < (heartbeat_interval * 4), (
        f"total preemption-to-return latency {elapsed_total:.3f}s exceeded "
        f"4x heartbeat interval — preemption is not bounded"
    )
