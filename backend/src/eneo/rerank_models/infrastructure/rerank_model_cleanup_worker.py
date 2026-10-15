"""Weekly lifecycle cleanup of soft-deleted rerank models.

A rerank model becomes a tombstone when it is soft-deleted (``deleted_at``
set). The only reference, ``assistants.rerank_model_id``, is ON DELETE SET
NULL: assistants that still point at the tombstone fall back to vector order
once it is gone, so nothing ever blocks the removal. The explicit check keeps
the shape of the other model-type workers.
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
from eneo.database.tables.ai_models_table import RerankModels
from eneo.main.container.container import Container
from eneo.worker.worker import Worker

logger = logging.getLogger(__name__)
worker: Any = Worker()


async def _find_candidates(session: AsyncSession, limit: int) -> list[Candidate]:
    stmt = (
        sa.select(RerankModels.id, RerankModels.nickname)
        .where(RerankModels.deleted_at.isnot(None))
        .order_by(RerankModels.deleted_at.asc().nulls_last())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(cast(UUID, row.id), cast(str, row.nickname)) for row in result.all()]


async def _has_blocking_refs(session: AsyncSession, model_id: UUID) -> bool:
    # assistants.rerank_model_id is SET NULL, never a blocker.
    return False


@worker.cron_job(hour=6, minute=0, weekday={6}, manages_own_session=True)  # Sun 6:00
async def cleanup_orphaned_rerank_models(container: Container) -> dict[str, Any]:
    session = cast(AsyncSession, container.session())
    return await run_model_lifecycle_cleanup(
        session=session,
        table=RerankModels,
        find_candidates=_find_candidates,
        has_blocking_refs=_has_blocking_refs,
        job_label="rerank model",
    )
