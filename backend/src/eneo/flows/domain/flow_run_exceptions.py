from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import ConflictException


@dataclass(slots=True)
class FlowRunConcurrencyLimitReachedError(Exception):
    max_concurrent_runs: int


@dataclass(eq=False)
class FlowRunNotFoundError(Exception):
    run_id: UUID
    tenant_id: UUID
    flow_id: UUID | None = None


class FlowRunIdempotencyRunDeletedError(ConflictException):
    """The idempotency key's run is being deleted: never replayed, never re-created."""

    def __init__(self) -> None:
        super().__init__(
            "The run created with this idempotency key is being deleted.",
            code=FlowApiErrorCode.RUN_IDEMPOTENCY_RUN_DELETED.value,
        )


@dataclass(eq=False)
class FlowRunPersistenceInvariantError(RuntimeError):
    operation: str
    run_id: UUID | None = None
    tenant_id: UUID | None = None
    flow_id: UUID | None = None


class FlowExecutionOwnershipLost(asyncio.CancelledError):
    pass
