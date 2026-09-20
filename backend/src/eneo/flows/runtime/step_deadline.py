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
from dataclasses import dataclass

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import TypedIOValidationException

# The executor's backstop fires this much after the budget, so a provider wait
# that reaches the deadline first can cancel its request with grace and report
# the provider-work disclosure itself.
STEP_DEADLINE_BACKSTOP_GRACE_SECONDS = 3.0


def _now() -> float:
    return asyncio.get_running_loop().time()


@dataclass(frozen=True, slots=True)
class StepDeadline:
    budget_seconds: float
    started_at: float
    expires_at: float

    @classmethod
    def start(cls, budget_seconds: float) -> StepDeadline:
        now = _now()
        budget = float(budget_seconds)
        return cls(budget_seconds=budget, started_at=now, expires_at=now + budget)

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
        provider_request_in_flight: bool = False,
    ) -> TypedIOValidationException:
        """The typed refusal for an exhausted budget, naming where it ran out."""
        completed_detail = f" ({completed})" if completed else ""
        disclosure = (
            " A provider request was in flight; the provider may still complete "
            "and bill it, so check the run before retrying."
            if provider_request_in_flight
            else ""
        )
        return TypedIOValidationException(
            f"Step {step_order}: execution budget of {self.budget_seconds:g}s "
            f"exhausted during {phase} after {self.elapsed():.0f}s"
            f"{completed_detail}.{disclosure} Raise the step's timeout_seconds in "
            "the flow definition (up to the deployment ceiling) or reduce the input.",
            code=FlowApiErrorCode.STEP_TIMEOUT.value,
        )


def require_step_budget(
    deadline: StepDeadline | None,
    *,
    step_order: int,
    phase: str,
    completed: str | None = None,
) -> None:
    """Refuse to start ``phase`` when the attempt's budget is already spent.

    No deadline means a caller outside an executor attempt (direct runtime
    use in tests); such work is bounded by its own provider wait only.
    """
    if deadline is not None and deadline.expired():
        raise deadline.timeout_error(
            step_order=step_order, phase=phase, completed=completed
        )
