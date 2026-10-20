"""Limits shared by an orchestrator and its local specialist executions.

The counters cover requests Eneo dispatches. They do not claim to measure work
performed inside an MCP server, including HTTP loopback leaf tools. Those
servers retain their existing per-call limits. Input bytes are admission
limits; actual provider token usage remains owned by the completion response.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import monotonic

from eneo.main.exceptions import OpenAIException


@dataclass(frozen=True)
class ExecutionLimits:
    consultations: int = 6
    model_requests: int = 24
    tool_calls: int = 48
    input_bytes: int = 1_048_576
    output_characters: int = 100_000
    duration_seconds: float = 180
    consultation_seconds: float = 60

    def __post_init__(self) -> None:
        if (
            min(
                self.consultations,
                self.model_requests,
                self.tool_calls,
                self.input_bytes,
                self.output_characters,
                self.duration_seconds,
                self.consultation_seconds,
            )
            <= 0
        ):
            raise ValueError("Execution limits must be positive")


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
    limits: ExecutionLimits = field(default_factory=ExecutionLimits)
    started_at: float = field(default_factory=monotonic)
    consultations: int = 0
    model_requests: int = 0
    tool_calls: int = 0
    input_bytes: int = 0
    output_characters: int = 0
    stopped: bool = False
    # Specialists execute serially. A lock belongs to the run, so a provider
    # emitting several delegation calls cannot create concurrent child runs.
    specialist_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    reference_prefixes: set[str] = field(default_factory=set[str])

    @property
    def remaining_seconds(self) -> float:
        return max(0, self.limits.duration_seconds - (monotonic() - self.started_at))

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

    def reserve_consultation(self) -> None:
        self.consultations = self._reserve(
            "consultations", self.consultations, self.limits.consultations
        )

    def reserve_model_request(self, input_bytes: int) -> None:
        # Check both before mutating either: a rejected request spends no
        # provider reservation and cannot reach the outbound transport.
        self.check_active()
        if input_bytes < 0:
            raise ValueError("Input size cannot be negative")
        if self.model_requests >= self.limits.model_requests:
            raise ExecutionLimitReached("model_requests")
        if self.input_bytes + input_bytes > self.limits.input_bytes:
            raise ExecutionLimitReached("input_bytes")
        self.model_requests += 1
        self.input_bytes += input_bytes

    def reserve_tool_call(self) -> None:
        self.tool_calls = self._reserve(
            "tool_calls", self.tool_calls, self.limits.tool_calls
        )

    def record_output(self, text: str) -> None:
        self.output_characters = self._reserve(
            "output_characters",
            self.output_characters,
            self.limits.output_characters,
            len(text),
        )

    @contextmanager
    def bind(self) -> Generator[None]:
        """Nested async tasks inherit this same budget, never fresh counters."""
        token = _CURRENT_BUDGET.set(self)
        try:
            yield
        finally:
            _CURRENT_BUDGET.reset(token)


_CURRENT_BUDGET: ContextVar[ExecutionBudget | None] = ContextVar(
    "assistant_execution_budget", default=None
)


def current_execution_budget() -> ExecutionBudget | None:
    return _CURRENT_BUDGET.get()
