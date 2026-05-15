from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.job_table import Jobs
from intric.main.models import Status as JobStatus


async def is_job_preempted(sess: AsyncSession, *, job_id: UUID) -> bool:
    """Crawler preemption is observed as an external FAILED job state."""
    result = await sess.execute(sa.select(Jobs.status).where(Jobs.id == job_id))
    return result.scalar_one_or_none() == JobStatus.FAILED.value
