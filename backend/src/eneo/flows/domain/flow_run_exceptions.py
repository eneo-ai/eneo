from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True)
class FlowRunConcurrencyLimitReachedError(Exception):
    max_concurrent_runs: int


@dataclass(eq=False)
class FlowRunNotFoundError(Exception):
    run_id: UUID
    tenant_id: UUID
    flow_id: UUID | None = None


@dataclass(eq=False)
class FlowRunPersistenceInvariantError(RuntimeError):
    operation: str
    run_id: UUID | None = None
    tenant_id: UUID | None = None
    flow_id: UUID | None = None


class FlowExecutionOwnershipLost(asyncio.CancelledError):
    pass


@dataclass(eq=False)
class FlowStepAttemptClosed(Exception):
    """A write for the attempt found it already closed, by the run's
    terminalization or by recovery: the run's stored outcome stands, and the
    step does no further work."""

    run_id: UUID
    step_id: UUID
    attempt_no: int
