"""Limits shared by an orchestrator and its local specialist executions.

The counters cover requests Eneo dispatches. They do not claim to measure work
performed inside an MCP server, including HTTP loopback leaf tools. Those
servers retain their existing per-call limits. Request bytes are a per-request
admission limit; actual provider token usage remains owned by the completion
response.

Specialists may not spend the reserves. They keep model requests, output
characters and time for the orchestrator's final synthesis, so an exhausted
budget still ends in an answer that names its gaps instead of a failed turn.
Time spent waiting for a user's tool approval is excluded from the deadlines.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from time import monotonic
from typing import TypeVar, cast

from eneo.main.exceptions import OpenAIException


@dataclass(frozen=True)
class ExecutionLimits:
    consultations: int = 6
    model_requests: int = 24
    tool_calls: int = 48
    # Largest single provider request. The context builder already bounds a
    # request by the model's window; this guards pathological payloads without
    # charging the re-sent conversation once per round.
    request_bytes: int = 4 * 1024 * 1024
    output_characters: int = 100_000
    duration_seconds: float = 180
    consultation_seconds: float = 60
    reserved_model_requests: int = 2
    reserved_output_characters: int = 8_000
    reserved_seconds: float = 20

    def __post_init__(self) -> None:
        if (
            min(
                self.consultations,
                self.model_requests,
                self.tool_calls,
                self.request_bytes,
                self.output_characters,
                self.duration_seconds,
                self.consultation_seconds,
            )
            <= 0
        ):
            raise ValueError("Execution limits must be positive")
        if not (
            0 <= self.reserved_model_requests < self.model_requests
            and 0 <= self.reserved_output_characters < self.output_characters
            and 0 <= self.reserved_seconds < self.duration_seconds
        ):
            raise ValueError("Reserves must be smaller than their limits")

    @classmethod
    def from_settings(cls) -> ExecutionLimits:
        from eneo.main.config import get_settings

        settings = get_settings()
        return cls(
            consultations=settings.orchestration_max_consultations,
            model_requests=settings.orchestration_max_model_requests,
            tool_calls=settings.orchestration_max_tool_calls,
            request_bytes=settings.orchestration_max_request_bytes,
            output_characters=settings.orchestration_max_output_characters,
            duration_seconds=settings.orchestration_timeout_seconds,
            consultation_seconds=settings.orchestration_consultation_timeout_seconds,
            reserved_model_requests=settings.orchestration_reserved_model_requests,
            reserved_output_characters=(
                settings.orchestration_reserved_output_characters
            ),
            reserved_seconds=settings.orchestration_reserved_seconds,
        )


class ExecutionLimitReached(OpenAIException):
    def __init__(self, limit: str) -> None:
        self.limit = limit
        super().__init__(
            "This turn reached its execution limit. Available results are incomplete.",
            code="execution_limit_reached",
            details={"limit": limit},
        )


@dataclass
class ExecutionBudget:
    limits: ExecutionLimits = field(default_factory=ExecutionLimits.from_settings)
    started_at: float = field(default_factory=monotonic)
    consultations: int = 0
    model_requests: int = 0
    tool_calls: int = 0
    largest_request_bytes: int = 0
    output_characters: int = 0
    paused_seconds: float = 0.0
    stopped: bool = False
    # True while a specialist executes; reserves then apply.
    child_active: bool = False
    # Specialists execute serially. A lock belongs to the run, so a provider
    # emitting several delegation calls cannot create concurrent child runs.
    specialist_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    reference_prefixes: set[str] = field(default_factory=set[str])
    _deadlines: list[asyncio.Timeout] = field(default_factory=list[asyncio.Timeout])
    _pause_depth: int = 0

    @property
    def elapsed_seconds(self) -> float:
        return monotonic() - self.started_at - self.paused_seconds

    @property
    def remaining_seconds(self) -> float:
        return max(0, self.limits.duration_seconds - self.elapsed_seconds)

    @property
    def child_seconds(self) -> float:
        """Deadline for one consultation, keeping the parent's time reserve."""
        return max(
            0,
            min(
                self.limits.consultation_seconds,
                self.remaining_seconds - self.limits.reserved_seconds,
            ),
        )

    def check_active(self) -> None:
        if self.stopped:
            raise ExecutionLimitReached("stopped")
        if self.remaining_seconds <= 0:
            raise ExecutionLimitReached("duration")

    def _reserve(self, name: str, used: int, limit: int, amount: int = 1) -> int:
        self.check_active()
        if amount < 0:
            raise ValueError("A budget reservation cannot be negative")
        if used + amount > limit:
            raise ExecutionLimitReached(name)
        return used + amount

    @property
    def child_model_request_limit(self) -> int:
        return self.limits.model_requests - self.limits.reserved_model_requests

    @property
    def child_output_limit(self) -> int:
        return self.limits.output_characters - self.limits.reserved_output_characters

    def _model_request_limit(self) -> int:
        if self.child_active:
            return self.child_model_request_limit
        return self.limits.model_requests

    def _output_limit(self) -> int:
        if self.child_active:
            return self.child_output_limit
        return self.limits.output_characters

    def ensure_child_capacity(self) -> None:
        """Refuse a new consultation that could only run on the parent's reserve."""
        self.check_active()
        if self.consultations >= self.limits.consultations:
            raise ExecutionLimitReached("consultations")
        if self.tool_calls >= self.limits.tool_calls:
            raise ExecutionLimitReached("tool_calls")
        if self.model_requests >= self.child_model_request_limit:
            raise ExecutionLimitReached("model_requests")
        if self.output_characters >= self.child_output_limit:
            raise ExecutionLimitReached("output_characters")
        if self.remaining_seconds <= self.limits.reserved_seconds:
            raise ExecutionLimitReached("duration")

    def reserve_consultation(self) -> None:
        self.consultations = self._reserve(
            "consultations", self.consultations, self.limits.consultations
        )

    def reserve_model_request(self, input_bytes: int) -> None:
        # Check everything before mutating anything: a rejected request spends
        # no provider reservation and cannot reach the outbound transport.
        self.check_active()
        if input_bytes < 0:
            raise ValueError("Input size cannot be negative")
        if self.model_requests >= self._model_request_limit():
            raise ExecutionLimitReached("model_requests")
        if input_bytes > self.limits.request_bytes:
            raise ExecutionLimitReached("request_bytes")
        self.model_requests += 1
        self.largest_request_bytes = max(self.largest_request_bytes, input_bytes)

    def reserve_tool_call(self) -> None:
        self.tool_calls = self._reserve(
            "tool_calls", self.tool_calls, self.limits.tool_calls
        )

    def record_output(self, text: str) -> None:
        self.output_characters = self._reserve(
            "output_characters",
            self.output_characters,
            self._output_limit(),
            len(text),
        )

    @contextmanager
    def bind(self) -> Generator[None]:
        """Nested async tasks inherit this same budget, never fresh counters."""
        token = _CURRENT_BUDGET.set(self)
        try:
            yield
        finally:
            restore_context_value(_CURRENT_BUDGET, token)

    @contextmanager
    def child_scope(self) -> Generator[None]:
        """Apply the parent's reserves while a specialist executes."""
        previous = self.child_active
        self.child_active = True
        try:
            yield
        finally:
            self.child_active = previous

    @contextmanager
    def deadline(self, timeout: asyncio.Timeout) -> Generator[None]:
        """Register a running deadline so a pause can push it back."""
        self._deadlines.append(timeout)
        try:
            yield
        finally:
            self._deadlines.remove(timeout)

    @asynccontextmanager
    async def pause(self) -> AsyncGenerator[None]:
        """Exclude time outside this execution from the deadlines.

        Used around a wait on the user (a tool approval) and around every
        yield that hands control to the consumer of an execution (the
        parent's bookkeeping, the response writer). The registered deadlines
        are suspended meanwhile and resume with the waited time added, so a
        deadline can only expire inside the execution's own awaits, where
        ``asyncio.timeout`` converts it to ``TimeoutError``. Pauses nest; only
        the outermost one accounts the time.
        """
        if self._pause_depth:
            self._pause_depth += 1
            try:
                yield
            finally:
                self._pause_depth -= 1
            return
        self._pause_depth = 1
        started = monotonic()
        suspended = [
            (timeout, timeout.when())
            for timeout in self._deadlines
            if not timeout.expired()
        ]
        for timeout, _ in suspended:
            timeout.reschedule(None)
        try:
            yield
        finally:
            self._pause_depth = 0
            waited = monotonic() - started
            self.paused_seconds += waited
            for timeout, when in suspended:
                if when is not None:
                    timeout.reschedule(when + waited)


_CURRENT_BUDGET: ContextVar[ExecutionBudget | None] = ContextVar(
    "assistant_execution_budget", default=None
)


T = TypeVar("T")


def restore_context_value(var: ContextVar[T], token: Token[T]) -> None:
    """Undo a ``set`` even when the generator that made it is finalized elsewhere.

    sse-starlette does not close the body iterator on a client disconnect, so
    the asyncio async-generator finalizer may run these ``finally`` blocks in a
    fresh context, where ``Token.reset`` raises ``ValueError``. Restoring by
    value keeps the owning context clean in the normal case and keeps the
    cleanup after this call running in the GC case.
    """
    try:
        var.reset(token)
    except ValueError:
        previous = token.old_value
        var.set(cast(T, None) if previous is Token.MISSING else previous)


def current_execution_budget() -> ExecutionBudget | None:
    return _CURRENT_BUDGET.get()
