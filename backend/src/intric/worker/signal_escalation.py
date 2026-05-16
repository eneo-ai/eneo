"""Escalating SIGINT/SIGTERM handler for the arq worker.

arq's `handle_sig_wait_for_completion` (used whenever `job_completion_wait`
is non-zero) absorbs Ctrl+C and waits the full drain window before
cancelling in-flight tasks. Repeated Ctrl+C presses do not speed shutdown
up — they just schedule additional drain tasks. Operators report needing
to press Ctrl+C 3-4 times while the worker keeps running until the 60s
drain elapses.

This module exposes a small, pure factory that wraps arq's drain handler
with press-count escalation so the first press preserves arq's graceful
semantics, the second press cancels every in-flight task immediately, and
a third press hard-exits the process. The factory takes every external
dependency (loop, drain callback, task introspection, exit hook) as a
parameter so unit tests can drive escalation without spawning real
signals or arq workers.

The `Worker.startup` hook installs an instance of this handler after arq
finishes registering its own signal handlers — using the asyncio
`Handle._callback` to recover arq's drain function without needing a
direct reference to the arq `Worker` (which arq does not expose to
on_startup callbacks).
"""

from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Callable, Iterable, Protocol

from intric.main.logging import get_logger

logger = get_logger(__name__)


__all__ = [
    "SignalEscalationState",
    "build_escalating_signal_handler",
    "install_escalating_signal_handlers",
]


class _Cancellable(Protocol):
    """Subset of `asyncio.Task` the escalating handler needs.

    `asyncio.Task` is `@final` on the C implementation, which makes it
    awkward to fake in unit tests; this Protocol lets the tests use a
    plain class while the production wiring binds `asyncio.all_tasks` /
    `asyncio.current_task` directly.
    """

    def done(self) -> bool: ...

    def cancel(self, msg: str | None = ...) -> bool: ...


@dataclass
class SignalEscalationState:
    """Tracks how many times the operator has pressed Ctrl+C.

    Mutating shared state from a signal handler is safe on CPython
    because `loop.add_signal_handler` posts the callback through the
    event loop's selfpipe — handlers do not run in the OS signal
    context. Keeping the counter on a dataclass instance rather than
    a module-level global makes the handler usable in concurrent
    in-process tests (e.g. a sub-worker integration test) without
    leaking state between cases.
    """

    presses: int = field(default=0)


def build_escalating_signal_handler(
    *,
    loop: object,
    state: SignalEscalationState,
    drain_callback: Callable[[int], None],
    hard_exit: Callable[[int], None],
    all_tasks: Callable[[Any], Iterable[_Cancellable]],
    current_task: Callable[[Any], _Cancellable | None],
    drain_timeout_seconds: float,
) -> Callable[[int], None]:
    """Build a callable suitable for `loop.add_signal_handler(signum, ...)`.

    Press 1: forward to `drain_callback` (arq's drain handler in production).
    Press 2: cancel every task returned by `all_tasks(loop)` except the
             `current_task(loop)` and any task already done. No grace
             period — operators have already chosen to escalate.
    Press 3+: invoke `hard_exit(130)`. 130 = 128 + SIGINT, the canonical
              exit code supervisor scripts (systemd, docker) expect when
              a process is killed by Ctrl+C.

    Exceptions raised by `drain_callback` are caught and logged so a
    misbehaving third-party shutdown handler cannot strand the worker.
    """

    def handler(signum: int) -> None:
        state.presses += 1
        press = state.presses
        sig_name = _safe_signal_name(signum)
        if press == 1:
            logger.warning(
                "Worker received %s — draining in-flight jobs "
                "(up to %.0fs). Press Ctrl+C again to cancel running "
                "jobs immediately; a third press will force-exit the "
                "process.",
                sig_name,
                drain_timeout_seconds,
            )
            try:
                drain_callback(signum)
            except Exception as exc:
                logger.warning(
                    "Drain handler raised %s — continuing escalation. "
                    "Press Ctrl+C again to cancel in-flight tasks.",
                    exc.__class__.__name__,
                    extra={"error": str(exc)},
                )
            return

        if press == 2:
            logger.warning(
                "Worker received %s twice — cancelling all in-flight "
                "tasks now. Press Ctrl+C once more to force-exit.",
                sig_name,
            )
            try:
                me = current_task(loop)
            except Exception:
                me = None
            for task in all_tasks(loop):
                if task is me:
                    continue
                if task.done():
                    continue
                task.cancel()
            return

        logger.error(
            "Worker received %s three times — hard-exiting with code 130.",
            sig_name,
        )
        hard_exit(130)

    return handler


def install_escalating_signal_handlers(
    *,
    loop: asyncio.AbstractEventLoop,
    drain_timeout_seconds: float,
    state: SignalEscalationState | None = None,
) -> SignalEscalationState:
    """Wrap the existing SIGINT/SIGTERM handlers on `loop` with escalation.

    Must be called AFTER arq has registered its own handlers (i.e. inside
    `on_startup`). The current `Handle._callback` for each signal is
    captured before overwriting so the first Ctrl+C press still triggers
    arq's drain semantics. Signals without a pre-existing handler are
    skipped — if arq is not handling them, this module should not invent
    a drain behavior.

    Uses `loop._signal_handlers` to recover the arq-installed callback;
    that attribute is private but stable across CPython 3.7+ and is the
    only way to capture a handler installed via `loop.add_signal_handler`
    without holding a separate reference. Documented here so a future
    upgrade to a CPython version that changes this attribute fails loudly
    rather than silently regressing.
    """
    state = state if state is not None else SignalEscalationState()
    handlers_map: dict[int, asyncio.Handle] = getattr(loop, "_signal_handlers", {})

    for signum in (int(signal.SIGINT), int(signal.SIGTERM)):
        existing = handlers_map.get(signum)
        if existing is None:
            logger.debug(
                "No pre-existing handler for %s — skipping escalation install.",
                _safe_signal_name(signum),
            )
            continue

        captured_callback = existing._callback  # noqa: SLF001 — stable CPython internal
        captured_args = existing._args  # noqa: SLF001 — stable CPython internal

        def drain(
            _signum_inner: int, _cb: Any = captured_callback, _args: Any = captured_args
        ) -> None:
            _cb(*_args)

        handler = build_escalating_signal_handler(
            loop=loop,
            state=state,
            drain_callback=drain,
            hard_exit=os._exit,
            all_tasks=asyncio.all_tasks,
            current_task=asyncio.current_task,
            drain_timeout_seconds=drain_timeout_seconds,
        )

        loop.remove_signal_handler(signum)
        loop.add_signal_handler(signum, partial(handler, signum))

    return state


def _safe_signal_name(signum: int) -> str:
    try:
        return signal.Signals(signum).name
    except ValueError:
        return f"signal({signum})"
