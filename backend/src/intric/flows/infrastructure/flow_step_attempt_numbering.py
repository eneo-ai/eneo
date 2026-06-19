"""Single owner of next attempt number allocation across normal execution and reruns."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.flow_tables import FlowStepAttempts


async def next_step_attempt_no(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    flow_run_id: UUID,
    step_id: UUID,
) -> int:
    max_attempt_no = await session.scalar(
        sa.select(sa.func.coalesce(sa.func.max(FlowStepAttempts.attempt_no), 0))
        .where(FlowStepAttempts.flow_run_id == flow_run_id)
        .where(FlowStepAttempts.tenant_id == tenant_id)
        .where(FlowStepAttempts.step_id == step_id)
    )
    return int(max_attempt_no or 0) + 1
