"""Run-cancellation signal for work that runs outside the step's LLM call.

The step runtime watches the run's cancellation state while a completion call
is in flight. Work that happens before that call exists (transcription during
step input resolution) has no such watcher, so the probe is published here as
ambient context: whoever waits on a slow external job reads it and stops when
the run is cancelled.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar

RunCancelProbe = Callable[[], Awaitable[bool]]


class FlowStepCancelledError(Exception):
    """The run was cancelled while a step was executing."""


_run_cancel_probe: ContextVar[RunCancelProbe | None] = ContextVar(
    "flow_run_cancel_probe", default=None
)


def current_run_cancel_probe() -> RunCancelProbe | None:
    return _run_cancel_probe.get()


@contextmanager
def run_cancel_probe_scope(probe: RunCancelProbe | None) -> Generator[None]:
    token = _run_cancel_probe.set(probe)
    try:
        yield
    finally:
        _run_cancel_probe.reset(token)
