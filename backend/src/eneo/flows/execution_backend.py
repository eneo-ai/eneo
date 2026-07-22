from __future__ import annotations

from typing import Protocol

from eneo.flows.flow_run_dispatch_request import FlowRunDispatchRequest


class FlowExecutionDispatchRejected(Exception):
    """The backend certifies that it did not accept the dispatch request."""


class FlowExecutionBackend(Protocol):
    """Dispatch-only execution backend contract for flow runs."""

    async def dispatch(
        self,
        *,
        request: FlowRunDispatchRequest,
    ) -> None: ...
