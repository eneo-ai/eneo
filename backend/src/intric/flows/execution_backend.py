from __future__ import annotations

from typing import Protocol
from uuid import UUID


class FlowExecutionBackend(Protocol):
    """Dispatch-only execution backend contract for flow runs."""

    async def dispatch(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        user_id: UUID | None,
    ) -> None: ...

