"""Weekly lifecycle cleanup of orphaned transcription models.

A transcription model becomes a tombstone when it is soft-deleted
(``deleted_at`` set) or migrated away from (``migrated_to_model_id`` set). The
row is kept so migration history and any lingering references still resolve.

Once nothing references it anymore it can be hard-deleted. A transcription
model's only direct usage reference is ``apps.transcription_model_id`` (FK
ON DELETE SET NULL — so the database would *not* stop a delete; the explicit
count below is the guard). Space links are config and were dropped on
delete/migrate. Migration-history rows keep denormalized model names, so the
SET NULL on their FK after hard-delete loses nothing user-visible.

This worker runs weekly and removes only models that satisfy ALL of:
  1. deleted_at IS NOT NULL OR migrated_to_model_id IS NOT NULL
  2. No other transcription model points to it via migrated_to_model_id
     (the self-FK is RESTRICT — it would block the delete)
  3. Zero apps referencing it
"""

import logging
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.ai_models.model_lifecycle_cleanup import (
    Candidate,
    run_model_lifecycle_cleanup,
)
from eneo.database.tables.ai_models_table import TranscriptionModels
from eneo.database.tables.app_table import Apps
from eneo.main.container.container import Container
from eneo.worker.worker import Worker

logger = logging.getLogger(__name__)
worker: Any = Worker()


async def _find_candidates(session: AsyncSession, limit: int) -> list[Candidate]:
    incoming_targets = (
        sa.select(TranscriptionModels.migrated_to_model_id)
        .where(TranscriptionModels.migrated_to_model_id.isnot(None))
        .scalar_subquery()
    )
    stmt = (
        sa.select(TranscriptionModels.id, TranscriptionModels.name)
        .where(
            sa.or_(
                TranscriptionModels.deleted_at.isnot(None),
                TranscriptionModels.migrated_to_model_id.isnot(None),
            ),
            TranscriptionModels.id.notin_(incoming_targets),
        )
        .order_by(TranscriptionModels.deleted_at.asc().nulls_last())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(cast(UUID, row.id), cast(str, row.name)) for row in result.all()]


async def _has_blocking_refs(session: AsyncSession, model_id: UUID) -> bool:
    app_refs = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Apps)
        .where(Apps.transcription_model_id == model_id)
    )
    return bool(app_refs)


@worker.cron_job(hour=4, minute=30, weekday={6}, manages_own_session=True)  # Sun 4:30
async def cleanup_orphaned_transcription_models(container: Container) -> dict[str, Any]:
    session = cast(AsyncSession, container.session())
    return await run_model_lifecycle_cleanup(
        session=session,
        table=TranscriptionModels,
        find_candidates=_find_candidates,
        has_blocking_refs=_has_blocking_refs,
        job_label="transcription model",
    )
