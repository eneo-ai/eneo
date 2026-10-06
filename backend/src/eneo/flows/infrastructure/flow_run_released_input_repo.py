from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import FlowRunReleasedInputs, FlowRuns
from eneo.flows.domain.flow_run_released_input import (
    FlowRunInputReleaseReason,
    FlowRunReleasedInput,
)


class FlowRunReleasedInputRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self, *, run_id: UUID, bindings: Sequence[tuple[UUID, UUID]], at: datetime
    ) -> int:
        """Called within the locked family's transaction after its owner proof."""
        if not bindings:
            return 0
        unique = tuple(dict.fromkeys(bindings))
        pairs = (
            sa.func.unnest(
                sa.bindparam(
                    "steps", [step for step, _ in unique], type_=ARRAY(sa.UUID())
                ),
                sa.bindparam(
                    "files", [file for _, file in unique], type_=ARRAY(sa.UUID())
                ),
            )
            .table_valued("step_id", "file_id")
            .render_derived()
        )
        statement = (
            insert(FlowRunReleasedInputs)
            .from_select(
                ["run_id", "step_id", "file_id", "released_at", "reason"],
                sa.select(
                    sa.literal(run_id, type_=sa.UUID()),
                    pairs.c.step_id,
                    pairs.c.file_id,
                    sa.literal(at, type_=sa.DateTime(timezone=True)),
                    sa.literal(FlowRunInputReleaseReason.TRANSCRIPTION_AUDIO_AFTER_USE),
                ).select_from(pairs),
            )
            .on_conflict_do_nothing()
        )
        rows = await self.session.scalars(
            statement.returning(FlowRunReleasedInputs.file_id)
        )
        return len(rows.all())

    async def list_for_run(
        self, *, run_id: UUID, tenant_id: UUID
    ) -> tuple[FlowRunReleasedInput, ...]:
        rows = await self.session.execute(
            sa.select(
                FlowRunReleasedInputs.step_id,
                FlowRunReleasedInputs.file_id,
                FlowRunReleasedInputs.released_at,
                FlowRunReleasedInputs.reason,
            )
            .join(FlowRuns, FlowRuns.id == FlowRunReleasedInputs.run_id)
            .where(FlowRuns.id == run_id, FlowRuns.tenant_id == tenant_id)
            .order_by(
                FlowRunReleasedInputs.released_at,
                FlowRunReleasedInputs.step_id,
                FlowRunReleasedInputs.file_id,
            )
        )
        return tuple(FlowRunReleasedInput.model_validate(row) for row in rows)

    async def step_ids(self, *, run_id: UUID, tenant_id: UUID) -> frozenset[UUID]:
        return frozenset(
            await self.session.scalars(
                sa.select(FlowRunReleasedInputs.step_id)
                .distinct()
                .join(FlowRuns, FlowRuns.id == FlowRunReleasedInputs.run_id)
                .where(FlowRuns.id == run_id, FlowRuns.tenant_id == tenant_id)
            )
        )
