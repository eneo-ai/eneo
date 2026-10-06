"""Persisted retention fences for repository and status probes."""

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.domain.retention import (
    ReceiptPhase,
    RetentionCategory,
    RetentionEntityKind,
    RetentionTrigger,
)
from eneo.database.tables.flow_tables import FlowRuns
from eneo.database.tables.retention_tables import RetentionReceipts
from eneo.flows.domain.flow_run_retention_policy import FLOWS_HISTORY_TASK


async def fence_flow_run(
    session: AsyncSession, *, run_id: UUID, tenant_id: UUID, flow_id: UUID
) -> UUID:
    now = datetime.now(timezone.utc)
    receipt = RetentionReceipts(
        task=FLOWS_HISTORY_TASK,
        entity_kind=RetentionEntityKind.FLOW_RUN.value,
        entity_id=run_id,
        category=RetentionCategory.RUN_RECORD.value,
        trigger=RetentionTrigger.SCHEDULED.value,
        tenant_id=tenant_id,
        flow_id=flow_id,
        phase=ReceiptPhase.DELETING.value,
        started_at=now,
        updated_at=now,
        manifest_completed_at=now,
    )
    session.add(receipt)
    await session.flush()
    await session.execute(
        sa.update(FlowRuns)
        .where(FlowRuns.id == run_id)
        .values(retention_receipt_id=receipt.id)
    )
    return receipt.id
