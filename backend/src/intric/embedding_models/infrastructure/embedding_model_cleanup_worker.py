"""Weekly lifecycle cleanup of orphaned embedding models.

An embedding model becomes a tombstone when it is soft-deleted (``deleted_at``
set). Embedding models are never *migrated* (switching embedding model means
re-embedding the underlying knowledge, not repointing references), so there is
no ``migrated_to_model_id`` to consider.

The tombstone is kept so historical ``info_blobs`` chunks keep resolving the
model that produced their vectors (the FK is ON DELETE SET NULL). It can be
hard-deleted only once nothing references it: collections, websites and
integration-knowledge are active configuration (a tenant delete is already
refused while those exist), and info_blobs are the historical blocker that
clears when the knowledge itself is removed.

This worker runs weekly and removes only models that satisfy ALL of:
  1. deleted_at IS NOT NULL
  2. Zero collections / websites / integration_knowledge / info_blobs referencing it
"""

import logging
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.ai_models.model_lifecycle_cleanup import (
    Candidate,
    run_model_lifecycle_cleanup,
)
from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.database.tables.integration_table import IntegrationKnowledge
from intric.database.tables.websites_table import Websites
from intric.main.container.container import Container
from intric.worker.worker import Worker

logger = logging.getLogger(__name__)
worker: Any = Worker()


async def _find_candidates(session: AsyncSession, limit: int) -> list[Candidate]:
    stmt = (
        sa.select(EmbeddingModels.id, EmbeddingModels.name)
        .where(EmbeddingModels.deleted_at.isnot(None))
        .order_by(EmbeddingModels.deleted_at.asc().nulls_last())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(cast(UUID, row.id), cast(str, row.name)) for row in result.all()]


async def _has_blocking_refs(session: AsyncSession, model_id: UUID) -> bool:
    counts = await session.execute(
        sa.select(
            sa.select(sa.func.count())
            .where(CollectionsTable.embedding_model_id == model_id)
            .correlate(None)
            .scalar_subquery()
            .label("collections"),
            sa.select(sa.func.count())
            .where(Websites.embedding_model_id == model_id)
            .correlate(None)
            .scalar_subquery()
            .label("websites"),
            sa.select(sa.func.count())
            .where(IntegrationKnowledge.embedding_model_id == model_id)
            .correlate(None)
            .scalar_subquery()
            .label("integrations"),
            sa.select(sa.func.count())
            .where(InfoBlobs.embedding_model_id == model_id)
            .correlate(None)
            .scalar_subquery()
            .label("info_blobs"),
        )
    )
    row = counts.one()
    return bool(row.collections or row.websites or row.integrations or row.info_blobs)


@worker.cron_job(hour=5, minute=0, weekday={6}, manages_own_session=True)  # Sun 5:00
async def cleanup_orphaned_embedding_models(container: Container) -> dict[str, Any]:
    session = cast(AsyncSession, container.session())
    return await run_model_lifecycle_cleanup(
        session=session,
        table=EmbeddingModels,
        find_candidates=_find_candidates,
        has_blocking_refs=_has_blocking_refs,
        job_label="embedding model",
    )
