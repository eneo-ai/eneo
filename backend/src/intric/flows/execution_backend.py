from __future__ import annotations

from typing import Protocol

from intric.flows.flow_run_dispatch_request import FlowRunDispatchRequest


class FlowExecutionBackend(Protocol):
    """Dispatch-only execution backend contract for flow runs."""

    async def dispatch(
        self,
        *,
        request: FlowRunDispatchRequest,
    ) -> None: ...
