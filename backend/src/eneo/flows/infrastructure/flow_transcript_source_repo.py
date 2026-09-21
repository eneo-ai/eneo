"""Insert-only transcript snapshots; the caller owns their publication transaction."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import FlowStepAttempts, FlowStepTranscriptSources
from eneo.flows.domain.transcript_source import (
    TranscriptSource,
    TranscriptSourceBounds,
    TranscriptSourceExportRow,
    TranscriptSourceReference,
    transcript_source_reference,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository


@dataclass(frozen=True, slots=True)
class TranscriptSourceExportMeasurement:
    row_count: int
    stored_json_bytes: int
    logical_json_bytes: int


@dataclass(frozen=True, slots=True)
class TranscriptSourceAttemptReference:
    step_id: UUID
    attempt_no: int
    reference: TranscriptSourceReference
    stored_reference: TranscriptSourceReference | None


class FlowTranscriptSourceRepository:
    def __init__(self, *, session: AsyncSession):
        self.session = session

    async def get_references_for_attempts(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        step_attempts: Sequence[tuple[UUID, int]],
    ) -> list[TranscriptSourceAttemptReference]:
        if not step_attempts:
            return []
        payload = FlowStepAttempts.input_payload_json
        transcription = sa.cast(
            sa.case(
                (
                    payload["schema_version"].astext == "flow-step-attempt-input.v1",
                    payload["resolved_input"]["transcription"],
                ),
                else_=payload["transcription"],
            ),
            JSONB,
        )
        rows = (
            await self.session.execute(
                sa.select(
                    FlowStepAttempts.step_id,
                    FlowStepAttempts.attempt_no,
                    transcription["source"].label("reference"),
                    FlowStepTranscriptSources.id.label("source_id"),
                    FlowStepTranscriptSources.source_hash,
                    *(
                        getattr(FlowStepTranscriptSources, name)
                        for name in TranscriptSourceBounds.model_fields
                    ),
                )
                .select_from(FlowStepAttempts)
                .outerjoin(
                    FlowStepTranscriptSources,
                    sa.and_(
                        FlowStepTranscriptSources.tenant_id
                        == FlowStepAttempts.tenant_id,
                        FlowStepTranscriptSources.flow_run_id
                        == FlowStepAttempts.flow_run_id,
                        FlowStepTranscriptSources.step_id == FlowStepAttempts.step_id,
                        FlowStepTranscriptSources.attempt_no
                        == FlowStepAttempts.attempt_no,
                    ),
                )
                .where(
                    FlowStepAttempts.tenant_id == tenant_id,
                    FlowStepAttempts.flow_run_id == run_id,
                    sa.tuple_(
                        FlowStepAttempts.step_id, FlowStepAttempts.attempt_no
                    ).in_(step_attempts),
                    sa.func.jsonb_typeof(transcription) == "object",
                    transcription.has_key("source"),
                )
            )
        ).mappings()
        references: list[TranscriptSourceAttemptReference] = []
        for row in rows:
            reference = transcript_source_reference(
                {"transcription": {"source": row["reference"]}}
            )
            assert reference is not None
            stored = (
                TranscriptSourceReference(
                    run_id=run_id,
                    step_id=row["step_id"],
                    attempt_no=row["attempt_no"],
                    source_hash=row["source_hash"],
                    bounds=TranscriptSourceBounds.model_validate(
                        {
                            name: row[name]
                            for name in TranscriptSourceBounds.model_fields
                        }
                    ),
                )
                if row["source_id"] is not None
                else None
            )
            references.append(
                TranscriptSourceAttemptReference(
                    step_id=row["step_id"],
                    attempt_no=row["attempt_no"],
                    reference=reference,
                    stored_reference=stored,
                )
            )
        return references

    async def count_for_export(
        self, *, tenant_id: UUID, run_id: UUID, ceiling: int
    ) -> int:
        candidates = (
            sa.select(FlowStepTranscriptSources.id)
            .where(
                FlowStepTranscriptSources.tenant_id == tenant_id,
                FlowStepTranscriptSources.flow_run_id == run_id,
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

    async def measure_for_export(
        self, *, tenant_id: UUID, run_id: UUID, candidate_limit: int
    ) -> TranscriptSourceExportMeasurement:
        columns = (
            FlowStepTranscriptSources.segments_json,
            FlowStepTranscriptSources.detail_json,
        )
        candidates = (
            sa.select(
                sum(
                    (
                        sa.func.coalesce(sa.func.pg_column_size(column), 0)
                        for column in columns
                    ),
                    sa.literal(0),
                ).label("stored"),
                sum(
                    (
                        sa.func.coalesce(
                            sa.func.octet_length(sa.cast(column, sa.Text)), 0
                        )
                        for column in columns
                    ),
                    sa.literal(0),
                ).label("logical"),
            )
            .where(
                FlowStepTranscriptSources.tenant_id == tenant_id,
                FlowStepTranscriptSources.flow_run_id == run_id,
            )
            .limit(candidate_limit)
            .subquery()
        )
        row = (
            await self.session.execute(
                sa.select(
                    sa.func.count(),
                    sa.func.coalesce(sa.func.sum(candidates.c.stored), 0),
                    sa.func.coalesce(sa.func.sum(candidates.c.logical), 0),
                )
            )
        ).one()
        return TranscriptSourceExportMeasurement(
            row_count=int(row[0]),
            stored_json_bytes=int(row[1]),
            logical_json_bytes=int(row[2]),
        )

    async def list_for_export(
        self, *, tenant_id: UUID, run_id: UUID, limit: int
    ) -> list[TranscriptSourceExportRow]:
        rows = await self.session.scalars(
            sa.select(FlowStepTranscriptSources)
            .where(
                FlowStepTranscriptSources.tenant_id == tenant_id,
                FlowStepTranscriptSources.flow_run_id == run_id,
            )
            .order_by(
                FlowStepTranscriptSources.step_id, FlowStepTranscriptSources.attempt_no
            )
            .limit(limit)
        )
        return [
            TranscriptSourceExportRow(
                id=row.id,
                tenant_id=row.tenant_id,
                flow_id=row.flow_id,
                run_id=row.flow_run_id,
                step_id=row.step_id,
                attempt_no=row.attempt_no,
                created_at=row.created_at,
                source_hash=row.source_hash,
                segments=row.segments_json,
                speaker_review=row.detail_json,
                bounds=TranscriptSourceBounds.model_validate(row, from_attributes=True),
            )
            for row in rows
        ]

    async def get_reference_for_attempt(
        self, *, tenant_id: UUID, run_id: UUID, step_id: UUID, attempt_no: int
    ) -> TranscriptSourceReference | None:
        row = (
            (
                await self.session.execute(
                    sa.select(
                        FlowStepTranscriptSources.source_hash,
                        *(
                            getattr(FlowStepTranscriptSources, name)
                            for name in TranscriptSourceBounds.model_fields
                        ),
                    ).where(
                        FlowStepTranscriptSources.tenant_id == tenant_id,
                        FlowStepTranscriptSources.flow_run_id == run_id,
                        FlowStepTranscriptSources.step_id == step_id,
                        FlowStepTranscriptSources.attempt_no == attempt_no,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return TranscriptSourceReference(
            run_id=run_id,
            step_id=step_id,
            attempt_no=attempt_no,
            source_hash=row["source_hash"],
            bounds=TranscriptSourceBounds.model_validate(
                {name: row[name] for name in TranscriptSourceBounds.model_fields}
            ),
        )

    async def insert(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        reference: TranscriptSourceReference,
        source: TranscriptSource,
    ) -> None:
        if (
            reference.source_hash != source.source_hash
            or reference.bounds != source.bounds
        ):
            raise ValueError("Transcript source does not match its reference.")
        await FlowRunRepository(session=self.session).lock_execution_ownership(
            run_id=reference.run_id, tenant_id=tenant_id
        )
        await self.session.execute(
            sa.insert(FlowStepTranscriptSources).values(
                tenant_id=tenant_id,
                flow_id=flow_id,
                flow_run_id=reference.run_id,
                step_id=reference.step_id,
                attempt_no=reference.attempt_no,
                source_hash=source.source_hash,
                segments_json=source.segments,
                detail_json=source.speaker_review,
                **source.bounds.model_dump(mode="json"),
            )
        )

    async def get_for_attempt(
        self, *, tenant_id: UUID, run_id: UUID, step_id: UUID, attempt_no: int
    ) -> TranscriptSource | None:
        row = await self.session.scalar(
            sa.select(FlowStepTranscriptSources).where(
                FlowStepTranscriptSources.tenant_id == tenant_id,
                FlowStepTranscriptSources.flow_run_id == run_id,
                FlowStepTranscriptSources.step_id == step_id,
                FlowStepTranscriptSources.attempt_no == attempt_no,
            )
        )
        if row is None:
            return None
        return TranscriptSource(
            segments=row.segments_json,
            speaker_review=row.detail_json,
            source_hash=row.source_hash,
            bounds=TranscriptSourceBounds.model_validate(row, from_attributes=True),
        )
