"""Escalating SIGINT/SIGTERM handler for the arq worker.

Without escalation, arq's `handle_sig_wait_for_completion` (used when
`job_completion_wait > 0`) absorbs Ctrl+C and waits the full drain
window before cancelling tasks. Repeated Ctrl+C presses just queue
additional drain tasks instead of speeding shutdown. Operators end up
mashing Ctrl+C 3-4 times and the worker still does not stop until the
60s drain elapses.

The escalation contract this test pins:
  press 1 → forward to the wrapped drain handler (preserve graceful semantics)
  press 2 → cancel every asyncio task on the loop, immediately
  press 3 → call the configured hard-exit hook with code 130

The handler is a pure function over its dependencies (loop, drain
callback, hard-exit callback) so the tests substitute fakes and assert
the escalation invariants without spawning real signals or a real arq
worker.
"""

from __future__ import annotations

import asyncio
import signal
from typing import Callable, cast

import pytest

from intric.worker.signal_escalation import (
    SignalEscalationState,
    build_escalating_signal_handler,
    install_escalating_signal_handlers,
)


class _FakeTask:
    """Lightweight task stand-in that records cancel() calls.

    `asyncio.Task` is final under pyright (`@final` on the C-impl). Faking
    via a Protocol-shaped class avoids the noise without weakening the
    invariant the test guards (escalation calls .cancel() on every task
    except the calling task).
    """

    def __init__(self, *, name: str, done: bool = False) -> None:
        self.name = name
        self._done = done
        self.cancel_calls: list[str | None] = []

    def done(self) -> bool:
        return self._done

    def cancel(self, msg: str | None = None) -> bool:  # noqa: ARG002 (msg unused)
        self.cancel_calls.append(msg)
        return True


def _make_handler(
    *,
    drain_calls: list[tuple[int, ...]],
    exit_calls: list[int],
    tasks: list[_FakeTask],
    current_task: _FakeTask | None,
) -> tuple[Callable[[int], None], SignalEscalationState]:
    """Build the multiplex handler with controllable side-effects so tests
    can drive escalation without touching real signals or the running loop."""
    loop = object()
    state = SignalEscalationState()

    def drain(signum: int) -> None:
        drain_calls.append((signum,))

    def hard_exit(code: int) -> None:
        exit_calls.append(code)

    def all_tasks(_loop: object) -> list[_FakeTask]:
        return tasks

    def get_current_task(_loop: object) -> _FakeTask | None:
        return current_task

    handler = build_escalating_signal_handler(
        loop=loop,
        state=state,
        drain_callback=drain,
        hard_exit=hard_exit,
        all_tasks=all_tasks,
        current_task=get_current_task,
        drain_timeout_seconds=60.0,
    )
    return handler, state


def test_first_press_forwards_to_drain_callback_only() -> None:
    drain_calls: list[tuple[int, ...]] = []
    exit_calls: list[int] = []
    tasks: list[_FakeTask] = [_FakeTask(name="worker-main")]
    handler, state = _make_handler(
        drain_calls=drain_calls,
        exit_calls=exit_calls,
        tasks=tasks,
        current_task=None,
    )

    handler(int(signal.SIGINT))

    assert drain_calls == [(int(signal.SIGINT),)]
    assert exit_calls == []
    assert tasks[0].cancel_calls == []
    assert state.presses == 1


def test_second_press_cancels_all_tasks_except_current() -> None:
    drain_calls: list[tuple[int, ...]] = []
    exit_calls: list[int] = []
    main_task = _FakeTask(name="worker-main")
    crawl_task = _FakeTask(name="crawl-job-1")
    feeder_task = _FakeTask(name="crawl-feeder")
    already_done = _FakeTask(name="already-done", done=True)
    tasks: list[_FakeTask] = [main_task, crawl_task, feeder_task, already_done]
    handler, state = _make_handler(
        drain_calls=drain_calls,
        exit_calls=exit_calls,
        tasks=tasks,
        current_task=main_task,
    )

    handler(int(signal.SIGINT))  # press 1 — drain
    handler(int(signal.SIGINT))  # press 2 — cancel

    assert state.presses == 2
    # The signal callback itself is not running inside a task in this fake,
    # so "current task" is only excluded if it shows up in all_tasks.
    assert main_task.cancel_calls == []  # current task is preserved
    assert crawl_task.cancel_calls == [None]
    assert feeder_task.cancel_calls == [None]
    assert already_done.cancel_calls == []  # already done, skip
    assert exit_calls == []


def test_third_press_hard_exits_with_130() -> None:
    drain_calls: list[tuple[int, ...]] = []
    exit_calls: list[int] = []
    tasks: list[_FakeTask] = []
    handler, state = _make_handler(
        drain_calls=drain_calls,
        exit_calls=exit_calls,
        tasks=tasks,
        current_task=None,
    )

    handler(int(signal.SIGINT))
    handler(int(signal.SIGINT))
    handler(int(signal.SIGINT))

    assert state.presses == 3
    # 130 = 128 + SIGINT (2) — the canonical exit code for Ctrl+C-killed
    # processes. Operators wiring this into supervisor scripts (systemd,
    # docker) expect that code; emitting something else (e.g. 1) would
    # mis-report the cause of death to the supervisor.
    assert exit_calls == [130]


def test_drain_callback_exception_does_not_break_escalation() -> None:
    """A buggy drain callback should not strand the worker. Escalation
    must keep working so a second Ctrl+C still cancels in-flight tasks.
    Without this guard a third-party shutdown handler raising in
    on_shutdown could leave the worker un-killable."""
    exit_calls: list[int] = []
    main_task = _FakeTask(name="worker-main")
    crawl_task = _FakeTask(name="crawl-job-1")
    tasks: list[_FakeTask] = [main_task, crawl_task]
    loop = object()
    state = SignalEscalationState()

    def boom(_signum: int) -> None:
        raise RuntimeError("drain handler exploded")

    def hard_exit(code: int) -> None:
        exit_calls.append(code)

    handler = build_escalating_signal_handler(
        loop=loop,
        state=state,
        drain_callback=boom,
        hard_exit=hard_exit,
        all_tasks=lambda _l: tasks,
        current_task=lambda _l: main_task,
        drain_timeout_seconds=60.0,
    )

    handler(int(signal.SIGINT))  # press 1 — drain raises, must be swallowed
    handler(int(signal.SIGINT))  # press 2 — must still cancel tasks

    assert state.presses == 2
    assert crawl_task.cancel_calls == [None]


def test_state_is_per_handler_so_multiple_workers_in_one_process_do_not_share() -> None:
    """The state object is supplied by the caller so a second worker
    (e.g. a sub-worker test harness) can keep its own press counter
    independent of the primary worker's escalation state."""
    state_a = SignalEscalationState()
    state_b = SignalEscalationState()
    drain_calls_a: list[int] = []
    drain_calls_b: list[int] = []
    loop_a = object()
    loop_b = object()

    handler_a = build_escalating_signal_handler(
        loop=loop_a,
        state=state_a,
        drain_callback=lambda s: drain_calls_a.append(s),
        hard_exit=lambda _c: None,
        all_tasks=lambda _l: [],
        current_task=lambda _l: None,
        drain_timeout_seconds=60.0,
    )
    handler_b = build_escalating_signal_handler(
        loop=loop_b,
        state=state_b,
        drain_callback=lambda s: drain_calls_b.append(s),
        hard_exit=lambda _c: None,
        all_tasks=lambda _l: [],
        current_task=lambda _l: None,
        drain_timeout_seconds=60.0,
    )

    handler_a(int(signal.SIGINT))
    handler_a(int(signal.SIGINT))
    handler_b(int(signal.SIGINT))

    assert state_a.presses == 2
    assert state_b.presses == 1
    assert drain_calls_a == [int(signal.SIGINT)]
    assert drain_calls_b == [int(signal.SIGINT)]


@pytest.mark.asyncio
async def test_real_loop_smoke_cancels_real_pending_task() -> None:
    """Integration-flavored smoke that proves the handler interoperates
    with a real asyncio loop and a real Task. The fake-based tests above
    pin contractual behavior; this one guards against accidental
    coupling to the fakes."""
    loop = asyncio.get_running_loop()
    state = SignalEscalationState()
    drain_called: list[int] = []
    exit_called: list[int] = []

    async def _sleeper() -> None:
        await asyncio.sleep(60)

    pending = asyncio.create_task(_sleeper(), name="sleeper")
    try:
        handler = build_escalating_signal_handler(
            loop=loop,
            state=state,
            drain_callback=lambda s: drain_called.append(s),
            hard_exit=lambda c: exit_called.append(c),
            all_tasks=asyncio.all_tasks,
            current_task=asyncio.current_task,
            drain_timeout_seconds=60.0,
        )

        handler(int(signal.SIGINT))  # press 1
        handler(int(signal.SIGINT))  # press 2

        # Yield once so the cancellation propagates.
        with pytest.raises(asyncio.CancelledError):
            await pending
    finally:
        if not pending.done():
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass

    assert drain_called == [int(signal.SIGINT)]
    assert exit_called == []
    assert state.presses == 2


@pytest.mark.asyncio
async def test_install_wraps_existing_signal_handler_and_first_press_forwards() -> None:
    """Codex AB-tier finding: the install path is the riskier surface
    (private-attribute walk, wrap-of-real-handler, sentinel logic) and
    was previously untested. Installing over a real `add_signal_handler`
    and asserting the captured handler still fires on press 1 pins the
    contract that the wrap is transparent for graceful drain.
    """
    loop = asyncio.get_running_loop()
    drain_called: list[int] = []

    def drain_handler(signum: int) -> None:
        drain_called.append(signum)

    # Install a stand-in "arq drain" handler so install_* has something
    # to wrap. We pick SIGUSR1 to avoid colliding with pytest's own
    # SIGINT plumbing.
    loop.add_signal_handler(signal.SIGUSR1, drain_handler, int(signal.SIGUSR1))

    try:
        # The install routine only knows about SIGINT/SIGTERM. To exercise
        # the wrap-of-real-handler path under SIGUSR1, we test the
        # registration shape by hand: install over our pretend SIGINT.
        loop.add_signal_handler(signal.SIGINT, drain_handler, int(signal.SIGINT))
        state = install_escalating_signal_handlers(
            loop=loop, drain_timeout_seconds=60.0
        )

        # Pull the freshly installed partial back out and invoke it as if
        # the signal had fired. asyncio routes signals through the loop's
        # selfpipe to this callable, so calling it directly is the same
        # code path the OS would trigger.
        handle = loop._signal_handlers[int(signal.SIGINT)]  # type: ignore[attr-defined]  # private attr, see signal_escalation.py
        installed = handle._callback  # noqa: SLF001
        installed()

        assert state.presses == 1
        assert drain_called == [int(signal.SIGINT)]
    finally:
        for sig in (signal.SIGINT, signal.SIGUSR1):
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, ValueError):
                pass


@pytest.mark.asyncio
async def test_install_with_no_existing_handler_leaves_state_pristine() -> None:
    """If arq is constructed with `handle_signals=False` (e.g. in a
    supervisor that owns signal handling), there will be no pre-existing
    handler on the loop. Install must skip silently rather than invent
    a drain behavior or raise."""
    loop = asyncio.get_running_loop()
    # Make sure no SIGINT handler exists on this loop.
    try:
        loop.remove_signal_handler(signal.SIGINT)
    except (NotImplementedError, ValueError):
        pass
    try:
        loop.remove_signal_handler(signal.SIGTERM)
    except (NotImplementedError, ValueError):
        pass

    state = install_escalating_signal_handlers(loop=loop, drain_timeout_seconds=60.0)

    # State counter untouched; signal handlers absent (the loop's
    # `_signal_handlers` may not even register the key).
    assert state.presses == 0
    handlers_map = loop._signal_handlers  # type: ignore[attr-defined]
    assert int(signal.SIGINT) not in handlers_map
    assert int(signal.SIGTERM) not in handlers_map


@pytest.mark.asyncio
async def test_install_is_idempotent_under_double_invocation() -> None:
    """Re-invoking `Worker.startup` (test harness re-entry, future
    warm-restart, etc.) must NOT wrap our own wrapper. Without the
    sentinel guard the second call would produce a 6-press ladder and
    pin a reference to the first wrapper indefinitely."""
    loop = asyncio.get_running_loop()
    drain_called: list[int] = []

    def drain_handler(signum: int) -> None:
        drain_called.append(signum)

    loop.add_signal_handler(signal.SIGINT, drain_handler, int(signal.SIGINT))

    try:
        first_state = install_escalating_signal_handlers(
            loop=loop, drain_timeout_seconds=60.0
        )
        # Second install passes a fresh state — if the sentinel didn't
        # short-circuit, the second wrap would route press 1 into the
        # first wrapper (not the user's drain) and silently double the
        # ladder.
        second_state = install_escalating_signal_handlers(
            loop=loop, drain_timeout_seconds=60.0
        )

        handle = loop._signal_handlers[int(signal.SIGINT)]  # type: ignore[attr-defined]
        installed = handle._callback  # noqa: SLF001
        installed()  # press 1

        assert first_state.presses == 1
        # The second call's state was never wired up — it never wraps
        # because the sentinel short-circuits. presses==0 proves the
        # second install did not register a new partial.
        assert second_state.presses == 0
        assert drain_called == [int(signal.SIGINT)]
    finally:
        try:
            loop.remove_signal_handler(signal.SIGINT)
        except (NotImplementedError, ValueError):
            pass


def test_install_with_non_dict_signal_handlers_skips_gracefully() -> None:
    """On a non-CPython loop (uvloop variants, future asyncio refactor)
    `_signal_handlers` may be a different shape. The installer must
    skip with a logged warning instead of crashing on AttributeError
    or returning a partially-installed escalation."""

    class _FakeLoop:
        _signal_handlers = "not a dict"  # type: ignore[assignment]

    loop = _FakeLoop()
    state = install_escalating_signal_handlers(
        loop=cast(asyncio.AbstractEventLoop, loop), drain_timeout_seconds=60.0
    )
    assert state.presses == 0
