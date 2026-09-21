"""Insert-only transcript snapshots; the caller owns their publication transaction."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import FlowStepTranscriptSources
from eneo.flows.domain.transcript_source import (
    TranscriptSource,
    TranscriptSourceBounds,
    TranscriptSourceReference,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository


class FlowTranscriptSourceRepository:
    def __init__(self, *, session: AsyncSession):
        self.session = session

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
