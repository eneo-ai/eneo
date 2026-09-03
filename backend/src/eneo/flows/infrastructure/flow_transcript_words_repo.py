"""Persistence owner for a transcription step's word timings.

Callers own the active database transaction. One row per (flow_run_id,
step_id); an in-run retry re-transcribes and replaces the row.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import FlowStepTranscriptWords as WordsTable
from eneo.flows.domain.transcript_words import FlowStepTranscriptWords


class FlowTranscriptWordsRepository:
    def __init__(self, *, session: AsyncSession):
        self.session = session

    async def get_for_step(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        tenant_id: UUID,
    ) -> FlowStepTranscriptWords | None:
        row = await self.session.scalar(
            sa.select(WordsTable)
            .where(WordsTable.flow_run_id == run_id)
            .where(WordsTable.step_id == step_id)
            .where(WordsTable.tenant_id == tenant_id)
        )
        if row is None:
            return None
        return FlowStepTranscriptWords.model_validate(row)

    async def upsert(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        run_id: UUID,
        step_id: UUID,
        segments_hash: str,
        alignment: str | None,
        words_json: list[dict[str, Any]],
    ) -> FlowStepTranscriptWords:
        stmt = pg_insert(WordsTable).values(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=run_id,
            step_id=step_id,
            segments_hash=segments_hash,
            alignment=alignment,
            words_json=words_json,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_flow_step_transcript_words_run_step",
            set_={
                "segments_hash": stmt.excluded.segments_hash,
                "alignment": stmt.excluded.alignment,
                "words_json": stmt.excluded.words_json,
                "updated_at": sa.func.now(),
            },
            where=WordsTable.tenant_id == tenant_id,
        ).returning(WordsTable)
        row = (await self.session.execute(stmt)).scalar_one()
        return FlowStepTranscriptWords.model_validate(row)

    async def delete_for_step(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        tenant_id: UUID,
    ) -> None:
        await self.session.execute(
            sa.delete(WordsTable)
            .where(WordsTable.flow_run_id == run_id)
            .where(WordsTable.step_id == step_id)
            .where(WordsTable.tenant_id == tenant_id)
        )
