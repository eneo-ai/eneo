from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Exists

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.flow_tables import (
    FlowRuns,
    Flows,
    FlowSteps,
)

_FLOW_MANAGED_ASSISTANT_ORIGIN = "flow_managed"


async def space_has_flow_delete_blockers(session: AsyncSession, space_id: UUID) -> bool:
    # Soft-deleted Flows count here: retained children can still block raw cascades.
    stmt = sa.select(
        _flow_run_history_exists(space_id)
        | _flow_step_exists(space_id)
        | _flow_managed_assistant_exists(space_id)
    )
    return bool(await session.scalar(stmt))


def _flow_run_history_exists(space_id: UUID) -> Exists:
    return (
        sa.select(sa.literal(True))
        .select_from(FlowRuns)
        .join(
            Flows,
            sa.and_(
                Flows.id == FlowRuns.flow_id,
                Flows.tenant_id == FlowRuns.tenant_id,
            ),
        )
        .where(Flows.space_id == space_id)
        .limit(1)
        .exists()
    )


def _flow_step_exists(space_id: UUID) -> Exists:
    return (
        sa.select(sa.literal(True))
        .select_from(FlowSteps)
        .join(
            Flows,
            sa.and_(
                Flows.id == FlowSteps.flow_id,
                Flows.tenant_id == FlowSteps.tenant_id,
            ),
        )
        .where(Flows.space_id == space_id)
        .limit(1)
        .exists()
    )


def _flow_managed_assistant_exists(space_id: UUID) -> Exists:
    return (
        sa.select(sa.literal(True))
        .select_from(Assistants)
        .where(Assistants.space_id == space_id)
        .where(Assistants.origin == _FLOW_MANAGED_ASSISTANT_ORIGIN)
        .limit(1)
        .exists()
    )
