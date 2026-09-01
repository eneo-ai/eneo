"""Persistence owner for flow transcript correction sets.

Callers own the active database transaction. One row per (flow_run_id,
step_id); writes replace the whole occurrence list under a compare-and-swap
revision so two editing surfaces never silently clobber each other.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import FlowTranscriptCorrections
from eneo.flows.domain.transcript_corrections import (
    TRANSCRIPT_CORRECTIONS_SCHEMA_VERSION,
    FlowTranscriptCorrectionSet,
    FlowTranscriptCorrectionsStaleRevisionError,
)
from eneo.flows.principal import FlowPrincipal


class FlowTranscriptCorrectionsRepository:
    def __init__(self, *, session: AsyncSession):
        self.session = session

    async def list_for_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
    ) -> list[FlowTranscriptCorrectionSet]:
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowTranscriptCorrections)
                    .where(FlowTranscriptCorrections.flow_run_id == run_id)
                    .where(FlowTranscriptCorrections.tenant_id == tenant_id)
                    .order_by(FlowTranscriptCorrections.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return [FlowTranscriptCorrectionSet.model_validate(row) for row in rows]

    async def get_for_step(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        tenant_id: UUID,
    ) -> FlowTranscriptCorrectionSet | None:
        row = await self.session.scalar(
            sa.select(FlowTranscriptCorrections)
            .where(FlowTranscriptCorrections.flow_run_id == run_id)
            .where(FlowTranscriptCorrections.step_id == step_id)
            .where(FlowTranscriptCorrections.tenant_id == tenant_id)
        )
        if row is None:
            return None
        return FlowTranscriptCorrectionSet.model_validate(row)

    async def save(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        run_id: UUID,
        step_id: UUID,
        occurrences_json: list[dict[str, Any]],
        segments_hash: str,
        expected_revision: int | None,
        principal: FlowPrincipal,
    ) -> FlowTranscriptCorrectionSet:
        """Create (expected_revision None) or CAS-replace the step's set."""
        principal_values = {
            "edited_by_principal_type": principal.principal_type.value,
            "edited_by_user_id": principal.principal_user_id,
            "edited_by_service_id": principal.principal_service_id,
        }
        if expected_revision is None:
            insert_stmt = (
                pg_insert(FlowTranscriptCorrections)
                .values(
                    tenant_id=tenant_id,
                    flow_id=flow_id,
                    flow_run_id=run_id,
                    step_id=step_id,
                    occurrences_json=occurrences_json,
                    segments_hash=segments_hash,
                    schema_version=TRANSCRIPT_CORRECTIONS_SCHEMA_VERSION,
                    **principal_values,
                )
                .on_conflict_do_nothing(
                    constraint="uq_flow_transcript_corrections_run_step",
                )
                .returning(FlowTranscriptCorrections)
            )
            row = (await self.session.execute(insert_stmt)).scalar_one_or_none()
            if row is None:
                raise FlowTranscriptCorrectionsStaleRevisionError(
                    expected_revision=None,
                    current_revision=await self._current_revision(
                        run_id=run_id, step_id=step_id, tenant_id=tenant_id
                    ),
                )
            return FlowTranscriptCorrectionSet.model_validate(row)

        update_stmt = (
            sa.update(FlowTranscriptCorrections)
            .where(FlowTranscriptCorrections.flow_run_id == run_id)
            .where(FlowTranscriptCorrections.step_id == step_id)
            .where(FlowTranscriptCorrections.tenant_id == tenant_id)
            .where(FlowTranscriptCorrections.revision == expected_revision)
            .values(
                occurrences_json=occurrences_json,
                segments_hash=segments_hash,
                revision=FlowTranscriptCorrections.revision + 1,
                schema_version=TRANSCRIPT_CORRECTIONS_SCHEMA_VERSION,
                updated_at=sa.func.now(),
                **principal_values,
            )
            .returning(FlowTranscriptCorrections)
        )
        row = (await self.session.execute(update_stmt)).scalar_one_or_none()
        if row is None:
            raise FlowTranscriptCorrectionsStaleRevisionError(
                expected_revision=expected_revision,
                current_revision=await self._current_revision(
                    run_id=run_id, step_id=step_id, tenant_id=tenant_id
                ),
            )
        return FlowTranscriptCorrectionSet.model_validate(row)

    async def _current_revision(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        tenant_id: UUID,
    ) -> int | None:
        return await self.session.scalar(
            sa.select(FlowTranscriptCorrections.revision)
            .where(FlowTranscriptCorrections.flow_run_id == run_id)
            .where(FlowTranscriptCorrections.step_id == step_id)
            .where(FlowTranscriptCorrections.tenant_id == tenant_id)
        )
