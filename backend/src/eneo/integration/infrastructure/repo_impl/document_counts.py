from collections.abc import Iterable
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa

from eneo.database.tables.info_blobs_table import InfoBlobs, active_info_blob_version

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def active_document_counts(
    session: "AsyncSession", knowledge_ids: Iterable[UUID]
) -> dict[UUID, int]:
    """Active info_blobs per integration knowledge, in one grouped query."""
    ids = list(knowledge_ids)
    if not ids:
        return {}
    stmt = (
        sa.select(InfoBlobs.integration_knowledge_id, sa.func.count())
        .where(
            InfoBlobs.integration_knowledge_id.in_(ids),
            active_info_blob_version(),
        )
        .group_by(InfoBlobs.integration_knowledge_id)
    )
    rows = await session.execute(stmt)
    return {row[0]: int(row[1]) for row in rows.all()}
