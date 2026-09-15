"""Persistence owner for flow transcript correction sets.

Callers own the active database transaction. One row per (flow_run_id,
step_id); writes replace the whole occurrence list under a compare-and-swap
revision so two editing surfaces never silently clobber each other.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import (
    FlowTranscriptCorrectionRevisions,
    FlowTranscriptCorrections,
)
from eneo.flows.domain.transcript_corrections import (
    TRANSCRIPT_CORRECTIONS_SCHEMA_VERSION,
    FlowTranscriptCorrectionRevision,
    FlowTranscriptCorrectionSet,
    FlowTranscriptCorrectionsStaleRevisionError,
)
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointEvidenceMeasurement,
)
from eneo.flows.principal import FlowPrincipal


class FlowTranscriptCorrectionsRepository:
    def __init__(self, *, session: AsyncSession):
        self.session = session

    async def get_revision(
        self,
        *,
        revision_id: UUID,
        tenant_id: UUID,
    ) -> FlowTranscriptCorrectionRevision | None:
        row = await self.session.scalar(
            sa.select(FlowTranscriptCorrectionRevisions)
            .where(FlowTranscriptCorrectionRevisions.id == revision_id)
            .where(FlowTranscriptCorrectionRevisions.tenant_id == tenant_id)
        )
        return (
            FlowTranscriptCorrectionRevision.model_validate(row)
            if row is not None
            else None
        )

    async def list_revisions_for_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        limit: int | None = None,
        logical_byte_budget: int | None = None,
    ) -> list[FlowTranscriptCorrectionRevision]:
        stmt = (
            sa.select(FlowTranscriptCorrectionRevisions)
            .where(FlowTranscriptCorrectionRevisions.flow_run_id == run_id)
            .where(FlowTranscriptCorrectionRevisions.tenant_id == tenant_id)
            .order_by(
                FlowTranscriptCorrectionRevisions.step_id,
                FlowTranscriptCorrectionRevisions.revision,
            )
        )
        if logical_byte_budget is not None:
            logical = sa.func.octet_length(
                sa.cast(FlowTranscriptCorrectionRevisions.occurrences_json, sa.Text)
            ) + sa.func.octet_length(
                sa.cast(FlowTranscriptCorrectionRevisions.speaker_edits_json, sa.Text)
            )
            candidates = (
                sa.select(
                    FlowTranscriptCorrectionRevisions.id,
                    FlowTranscriptCorrectionRevisions.step_id,
                    FlowTranscriptCorrectionRevisions.revision,
                    logical.label("logical"),
                )
                .where(
                    FlowTranscriptCorrectionRevisions.flow_run_id == run_id,
                    FlowTranscriptCorrectionRevisions.tenant_id == tenant_id,
                )
                .order_by(
                    FlowTranscriptCorrectionRevisions.step_id,
                    FlowTranscriptCorrectionRevisions.revision,
                )
            )
            if limit is not None:
                candidates = candidates.limit(limit)
            bounded = candidates.subquery()
            ranked = sa.select(
                bounded.c.id,
                sa.func.sum(bounded.c.logical)
                .over(order_by=(bounded.c.step_id, bounded.c.revision))
                .label("cumulative"),
            ).subquery()
            stmt = stmt.where(
                FlowTranscriptCorrectionRevisions.id.in_(
                    sa.select(ranked.c.id).where(
                        ranked.c.cumulative <= logical_byte_budget
                    )
                )
            )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = await self.session.scalars(stmt)
        return [FlowTranscriptCorrectionRevision.model_validate(row) for row in rows]

    async def get_revision_for_step(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        tenant_id: UUID,
        revision: int,
        logical_byte_budget: int,
    ) -> tuple[FlowTranscriptCorrectionRevision | None, tuple[int, int] | None]:
        metadata = (
            await self.session.execute(
                sa.select(
                    FlowTranscriptCorrectionRevisions.id,
                    sa.func.octet_length(
                        sa.cast(
                            FlowTranscriptCorrectionRevisions.occurrences_json, sa.Text
                        )
                    )
                    + sa.func.octet_length(
                        sa.cast(
                            FlowTranscriptCorrectionRevisions.speaker_edits_json,
                            sa.Text,
                        )
                    ),
                ).where(
                    FlowTranscriptCorrectionRevisions.flow_run_id == run_id,
                    FlowTranscriptCorrectionRevisions.step_id == step_id,
                    FlowTranscriptCorrectionRevisions.tenant_id == tenant_id,
                    FlowTranscriptCorrectionRevisions.revision == revision,
                )
            )
        ).one_or_none()
        if metadata is None:
            return None, None
        if metadata[1] > logical_byte_budget:
            return None, (revision, int(metadata[1]))
        return await self.get_revision(
            revision_id=metadata[0], tenant_id=tenant_id
        ), None

    async def list_revisions(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        tenant_id: UUID,
        after_revision: int | None,
        limit: int,
        logical_byte_budget: int,
    ) -> tuple[list[FlowTranscriptCorrectionRevision], bool, tuple[int, int] | None]:
        candidates = (
            sa.select(
                FlowTranscriptCorrectionRevisions.id,
                FlowTranscriptCorrectionRevisions.revision,
                (
                    sa.func.octet_length(
                        sa.cast(
                            FlowTranscriptCorrectionRevisions.occurrences_json, sa.Text
                        )
                    )
                    + sa.func.octet_length(
                        sa.cast(
                            FlowTranscriptCorrectionRevisions.speaker_edits_json,
                            sa.Text,
                        )
                    )
                ).label("logical"),
            )
            .where(
                FlowTranscriptCorrectionRevisions.flow_run_id == run_id,
                FlowTranscriptCorrectionRevisions.step_id == step_id,
                FlowTranscriptCorrectionRevisions.tenant_id == tenant_id,
                FlowTranscriptCorrectionRevisions.revision > (after_revision or 0),
            )
            .order_by(FlowTranscriptCorrectionRevisions.revision)
            .limit(limit + 1)
            .subquery()
        )
        ranked = sa.select(
            candidates.c.id,
            candidates.c.revision,
            candidates.c.logical,
            sa.func.sum(candidates.c.logical)
            .over(order_by=candidates.c.revision)
            .label("cumulative"),
            sa.func.row_number().over(order_by=candidates.c.revision).label("position"),
        ).subquery()
        metadata = (
            await self.session.execute(
                sa.select(ranked)
                .where(
                    sa.or_(
                        ranked.c.position == 1,
                        ranked.c.cumulative - ranked.c.logical <= logical_byte_budget,
                    )
                )
                .order_by(ranked.c.position)
            )
        ).all()
        admitted = [
            row.id for row in metadata[:limit] if row.cumulative <= logical_byte_budget
        ]
        obstructing = None
        if len(metadata) > len(admitted):
            next_row = metadata[len(admitted)]
            if next_row.cumulative > logical_byte_budget:
                obstructing = (int(next_row.revision), int(next_row.logical))
        rows: Sequence[FlowTranscriptCorrectionRevisions] = (
            (
                await self.session.scalars(
                    sa.select(FlowTranscriptCorrectionRevisions)
                    .where(FlowTranscriptCorrectionRevisions.id.in_(admitted))
                    .order_by(FlowTranscriptCorrectionRevisions.revision)
                )
            ).all()
            if admitted
            else []
        )
        return (
            [FlowTranscriptCorrectionRevision.model_validate(row) for row in rows],
            len(metadata) > len(admitted),
            obstructing,
        )

    async def _insert_revision(self, row: FlowTranscriptCorrections) -> None:
        await self.session.execute(
            sa.insert(FlowTranscriptCorrectionRevisions).values(
                tenant_id=row.tenant_id,
                correction_set_id=row.id,
                flow_id=row.flow_id,
                flow_run_id=row.flow_run_id,
                step_id=row.step_id,
                revision=row.revision,
                occurrences_json=row.occurrences_json,
                speaker_edits_json=row.speaker_edits_json,
                segments_hash=row.segments_hash,
                edited_by_user_id=row.edited_by_user_id,
                edited_by_service_id=row.edited_by_service_id,
                edited_by_principal_type=row.edited_by_principal_type,
            )
        )

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

    async def copy_snapshot(
        self, *, corrections: FlowTranscriptCorrectionSet, run_id: UUID
    ) -> None:
        """Keep the source editor and revision on a newly created run's immutable import."""
        values = corrections.model_dump(exclude={"id", "flow_run_id"})
        values["edited_by_principal_type"] = corrections.edited_by_principal_type.value
        await self.session.execute(
            sa.insert(FlowTranscriptCorrections).values(**values, flow_run_id=run_id)
        )

    async def save(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        run_id: UUID,
        step_id: UUID,
        occurrences_json: list[dict[str, Any]],
        speaker_edits_json: list[dict[str, Any]],
        segments_hash: str,
        expected_revision: int | None,
        principal: FlowPrincipal,
        schema_version: int = TRANSCRIPT_CORRECTIONS_SCHEMA_VERSION,
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
                    speaker_edits_json=speaker_edits_json,
                    segments_hash=segments_hash,
                    schema_version=schema_version,
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
            await self._insert_revision(row)
            return FlowTranscriptCorrectionSet.model_validate(row)

        update_stmt = (
            sa.update(FlowTranscriptCorrections)
            .where(FlowTranscriptCorrections.flow_run_id == run_id)
            .where(FlowTranscriptCorrections.step_id == step_id)
            .where(FlowTranscriptCorrections.tenant_id == tenant_id)
            .where(FlowTranscriptCorrections.revision == expected_revision)
            .values(
                occurrences_json=occurrences_json,
                speaker_edits_json=speaker_edits_json,
                segments_hash=segments_hash,
                revision=FlowTranscriptCorrections.revision + 1,
                schema_version=schema_version,
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
        await self._insert_revision(row)
        return FlowTranscriptCorrectionSet.model_validate(row)

    async def measure_revision_evidence_row_count(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        ceiling: int,
    ) -> int:
        candidates = (
            sa.select(FlowTranscriptCorrectionRevisions.id)
            .where(
                FlowTranscriptCorrectionRevisions.flow_run_id == run_id,
                FlowTranscriptCorrectionRevisions.tenant_id == tenant_id,
            )
            .limit(ceiling + 1)
            .subquery()
        )
        return int(
            await self.session.scalar(
                sa.select(sa.func.count()).select_from(candidates)
            )
            or 0
        )

    async def measure_revision_evidence(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        candidate_limit: int | None = None,
    ) -> FlowRunReviewCheckpointEvidenceMeasurement:
        stmt = sa.select(
            (
                sa.func.octet_length(
                    sa.cast(FlowTranscriptCorrectionRevisions.occurrences_json, sa.Text)
                )
                + sa.func.octet_length(
                    sa.cast(
                        FlowTranscriptCorrectionRevisions.speaker_edits_json, sa.Text
                    )
                )
            ).label("logical"),
            (
                sa.func.pg_column_size(
                    FlowTranscriptCorrectionRevisions.occurrences_json
                )
                + sa.func.pg_column_size(
                    FlowTranscriptCorrectionRevisions.speaker_edits_json
                )
            ).label("stored"),
        ).where(
            FlowTranscriptCorrectionRevisions.flow_run_id == run_id,
            FlowTranscriptCorrectionRevisions.tenant_id == tenant_id,
        )
        if candidate_limit is not None:
            stmt = stmt.limit(candidate_limit)
        candidates = stmt.subquery()
        row = (
            await self.session.execute(
                sa.select(
                    sa.func.count(),
                    sa.func.coalesce(sa.func.sum(candidates.c.stored), 0),
                    sa.func.coalesce(sa.func.sum(candidates.c.logical), 0),
                )
            )
        ).one()
        return FlowRunReviewCheckpointEvidenceMeasurement(
            row_count=int(row[0]),
            stored_json_bytes=int(row[1]),
            logical_json_bytes=int(row[2]),
        )

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
