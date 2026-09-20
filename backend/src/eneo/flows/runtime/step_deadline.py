"""One wall-clock budget per step attempt.

The executor starts it once around a step's handler and hands the same
instance to every dependency built for that attempt, so mapped items,
preparation (including transcription), retrieval, provider requests and
finalization all spend from one budget. A phase that is about to start
external work checks what is left first; the executor's outer timeout is the
backstop for work that cannot check.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from eneo.flows.enums import FlowStepPhase
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import TypedIOValidationException

# The executor's backstop fires this much after the budget, so a provider wait
# that reaches the deadline first can cancel its request with grace and report
# the provider-work disclosure itself.
STEP_DEADLINE_BACKSTOP_GRACE_SECONDS = 3.0


def _now() -> float:
    return asyncio.get_running_loop().time()


class StepDeadlineExceeded(TypedIOValidationException):
    def __init__(
        self,
        message: str,
        *,
        step_phase: FlowStepPhase | None,
        completed_items: int | None,
        total_items: int | None,
        provider_work_may_have_completed: bool | None,
    ) -> None:
        super().__init__(message, code=FlowApiErrorCode.STEP_TIMEOUT.value)
        self.step_phase = step_phase
        self.completed_items = completed_items
        self.total_items = total_items
        self.provider_work_may_have_completed = provider_work_may_have_completed


@dataclass(frozen=True, slots=True)
class StepDeadline:
    budget_seconds: float
    started_at: float
    expires_at: float
    invocation_limited: bool = False

    @classmethod
    def start(
        cls, budget_seconds: float, *, invocation_limited: bool = False
    ) -> StepDeadline:
        now = _now()
        budget = float(budget_seconds)
        return cls(
            budget_seconds=budget,
            started_at=now,
            expires_at=now + budget,
            invocation_limited=invocation_limited,
        )

    def remaining(self) -> float:
        return max(0.0, self.expires_at - _now())

    def elapsed(self) -> float:
        return max(0.0, _now() - self.started_at)

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def timeout_error(
        self,
        *,
        step_order: int,
        phase: str,
        completed: str | None = None,
        provider_request_in_flight: bool | None = None,
    ) -> StepDeadlineExceeded:
        """The typed refusal for an exhausted budget, naming where it ran out.

        Facts the caller does not know (mapped progress, whether a provider
        request is in flight) come from the attempt's published scope.
        """
        scope = _scope.get()
        if completed is None and scope is not None:
            completed = scope.progress
        provider_work_may_have_completed = (
            bool(
                provider_request_in_flight
                or scope.provider_request_in_flight
                or scope.provider_outcome_unresolved
            )
            if scope is not None
            else provider_request_in_flight
        )
        completed_detail = f" ({completed})" if completed else ""
        if provider_work_may_have_completed is True:
            disclosure = (
                " A provider request has an unknown outcome; the provider may still "
                "complete and bill it, so check the run before retrying."
            )
        elif provider_work_may_have_completed is False:
            disclosure = (
                " No provider request was sent."
                if scope is not None and scope.phase is FlowStepPhase.STEP_EXECUTION
                else " No provider request was in flight when the budget ran out."
            )
        else:
            disclosure = (
                " Provider work may have started; check the run before retrying."
            )
        recovery = (
            " The run's total budget was exhausted. Reduce the input or increase "
            "the worker invocation timeout."
            if self.invocation_limited
            else " Raise the step's timeout_seconds in the flow definition "
            "(up to the deployment ceiling) or reduce the input."
        )
        return StepDeadlineExceeded(
            f"Step {step_order}: execution budget of {self.budget_seconds:g}s "
            f"exhausted during {phase} after {self.elapsed():.0f}s"
            f"{completed_detail}.{disclosure}{recovery}",
            step_phase=scope.phase if scope is not None else None,
            completed_items=scope.completed_items if scope is not None else None,
            total_items=scope.total_items if scope is not None else None,
            provider_work_may_have_completed=provider_work_may_have_completed,
        )


@dataclass(slots=True)
class StepDeadlineScope:
    """The attempt's budget as ambient context.

    Published by the executor around the handler so work it cannot reach by
    parameter (transcription chunks, remote job submission) can refuse to
    start once the budget is spent, and so the timeout message can name the
    mapped progress and the provider activity or unresolved outcome the executor's
    backstop would otherwise not know about.
    """

    deadline: StepDeadline
    step_order: int
    progress: str | None = None
    phase: FlowStepPhase | None = None
    completed_items: int | None = None
    total_items: int | None = None
    provider_request_in_flight: bool = False
    provider_outcome_unresolved: bool = False


_scope: ContextVar[StepDeadlineScope | None] = ContextVar(
    "flow_step_deadline_scope", default=None
)


def current_step_deadline_scope() -> StepDeadlineScope | None:
    return _scope.get()


@contextmanager
def step_deadline_scope(
    deadline: StepDeadline, *, step_order: int
) -> Generator[StepDeadlineScope]:
    scope = StepDeadlineScope(deadline=deadline, step_order=step_order)
    token = _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.reset(token)


def record_step_progress(
    progress: str, *, completed_items: int | None = None, total_items: int | None = None
) -> None:
    """What a mapped step has completed so far, for the timeout message."""
    scope = _scope.get()
    if scope is not None:
        scope.progress = progress
        scope.completed_items = completed_items
        scope.total_items = total_items


def record_step_phase(phase: FlowStepPhase) -> None:
    scope = _scope.get()
    if scope is not None:
        scope.phase = phase


def mark_provider_request_in_flight(in_flight: bool) -> None:
    scope = _scope.get()
    if scope is not None:
        scope.provider_request_in_flight = in_flight


def settle_provider_request(*, known: bool) -> None:
    """A settled request cannot resolve an earlier request's unknown outcome."""
    scope = _scope.get()
    if scope is not None:
        if not known and scope.provider_request_in_flight:
            scope.provider_outcome_unresolved = True
        scope.provider_request_in_flight = False


def budget_refusal(*, phase: str) -> TypedIOValidationException | None:
    """The refusal for ``phase`` when the published budget is spent, or None.

    For callers that must settle a receipt before raising.
    """
    scope = _scope.get()
    if scope is None or not scope.deadline.expired():
        return None
    return scope.deadline.timeout_error(
        step_order=scope.step_order, phase=phase, provider_request_in_flight=False
    )


def require_step_budget(
    deadline: StepDeadline | None = None,
    *,
    phase: str,
    step_order: int | None = None,
    completed: str | None = None,
) -> None:
    """Refuse to start ``phase`` when the attempt's budget is already spent.

    ``deadline`` defaults to the published scope's; with neither (direct
    runtime use in tests, a transcription outside a flow attempt) there is
    no budget to refuse against.
    """
    scope = _scope.get()
    resolved = (
        deadline
        if deadline is not None
        else (scope.deadline if scope is not None else None)
    )
    if resolved is None or not resolved.expired():
        return
    if step_order is None:
        step_order = scope.step_order if scope is not None else 0
    raise resolved.timeout_error(
        step_order=step_order,
        phase=phase,
        completed=completed,
        provider_request_in_flight=False,
    )
