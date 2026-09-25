"""Weekly lifecycle cleanup of orphaned image models.

An image model becomes a tombstone when it is soft-deleted (``deleted_at``
set). Its only consumer is the built-in capability provider row on
``mcp_servers``, whose FK is ON DELETE RESTRICT and whose reference blocks the
soft delete in the first place, so a tombstone normally has no references
left. The explicit count keeps the run quiet if one ever does (manual DB
edits): the RESTRICT would fail the delete loudly otherwise.

This worker runs weekly and removes only models that satisfy ALL of:
  1. deleted_at IS NOT NULL
  2. Zero mcp_servers rows referencing it
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
from eneo.database.tables.ai_models_table import ImageModels
from eneo.database.tables.mcp_server_table import MCPServers
from eneo.main.container.container import Container
from eneo.worker.worker import Worker

logger = logging.getLogger(__name__)
worker: Any = Worker()


async def _find_candidates(session: AsyncSession, limit: int) -> list[Candidate]:
    stmt = (
        sa.select(ImageModels.id, ImageModels.nickname)
        .where(ImageModels.deleted_at.isnot(None))
        .order_by(ImageModels.deleted_at.asc().nulls_last())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(cast(UUID, row.id), cast(str, row.nickname)) for row in result.all()]


async def _has_blocking_refs(session: AsyncSession, model_id: UUID) -> bool:
    refs = await session.scalar(
        sa.select(sa.func.count())
        .select_from(MCPServers)
        .where(MCPServers.image_model_id == model_id)
    )
    return bool(refs)


@worker.cron_job(hour=5, minute=30, weekday={6}, manages_own_session=True)  # Sun 5:30
async def cleanup_orphaned_image_models(container: Container) -> dict[str, Any]:
    session = cast(AsyncSession, container.session())
    return await run_model_lifecycle_cleanup(
        session=session,
        table=ImageModels,
        find_candidates=_find_candidates,
        has_blocking_refs=_has_blocking_refs,
        job_label="image model",
    )
