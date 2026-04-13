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
        principal_type: str | None = None,
        principal_user_id: UUID | None = None,
        principal_api_key_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> None: ...
