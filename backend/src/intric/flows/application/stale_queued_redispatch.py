from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, TypeAlias

from intric.flows.execution_backend import FlowExecutionBackend
from intric.flows.flow_run_dispatch_request import (
    FlowRunDispatchSource,
    build_flow_run_dispatch_request,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StaleQueuedRedispatchNotClaimed:
    kind: Literal["not_claimed"] = "not_claimed"


@dataclass(frozen=True, slots=True)
class StaleQueuedRedispatchInvalidRequest:
    run: FlowRunDispatchSource
    error: ValueError
    kind: Literal["invalid_dispatch_request"] = "invalid_dispatch_request"


@dataclass(frozen=True, slots=True)
class StaleQueuedRedispatchDispatched:
    run: FlowRunDispatchSource
    kind: Literal["dispatched"] = "dispatched"


@dataclass(frozen=True, slots=True)
class StaleQueuedRedispatchDispatchFailed:
    run: FlowRunDispatchSource
    error: Exception
    kind: Literal["dispatch_failed"] = "dispatch_failed"


StaleQueuedRedispatchResult: TypeAlias = (
    StaleQueuedRedispatchNotClaimed
    | StaleQueuedRedispatchInvalidRequest
    | StaleQueuedRedispatchDispatched
    | StaleQueuedRedispatchDispatchFailed
)
StaleQueuedRedispatchClaim: TypeAlias = Callable[
    [], Awaitable[FlowRunDispatchSource | None]
]


class StaleQueuedRedispatchDispatchError(RuntimeError):
    """Carry a claimed run and dispatch failure from service to API audit policy."""

    def __init__(self, *, run: FlowRunDispatchSource, cause: Exception) -> None:
        self.run = run
        self.cause = cause
        message = str(cause).strip() or cause.__class__.__name__
        super().__init__(message)


async def redispatch_stale_queued_run(
    *,
    claim_run: StaleQueuedRedispatchClaim,
    backend: FlowExecutionBackend,
) -> StaleQueuedRedispatchResult:
    claimed = await claim_run()
    if claimed is None:
        return StaleQueuedRedispatchNotClaimed()

    try:
        dispatch_request = build_flow_run_dispatch_request(claimed)
    except ValueError as exc:
        logger.warning(
            "Skipping redispatch for run with invalid principal",
            extra={
                "run_id": str(claimed.id),
                "tenant_id": str(claimed.tenant_id),
            },
        )
        return StaleQueuedRedispatchInvalidRequest(run=claimed, error=exc)

    try:
        await backend.dispatch(request=dispatch_request)
    except Exception as exc:
        logger.exception(
            "Failed to redispatch stale queued flow run",
            extra={
                "run_id": str(claimed.id),
                "flow_id": str(claimed.flow_id),
                "tenant_id": str(claimed.tenant_id),
            },
        )
        return StaleQueuedRedispatchDispatchFailed(run=claimed, error=exc)

    return StaleQueuedRedispatchDispatched(run=claimed)
