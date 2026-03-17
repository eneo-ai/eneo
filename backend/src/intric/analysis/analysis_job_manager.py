# MIT License

from datetime import datetime, timedelta, timezone
from uuid import UUID

import orjson
import redis.asyncio as aioredis

from intric.analysis.analysis import AnalysisJobStatus
from intric.analysis.analysis_job import AnalysisJob
from intric.main.logging import get_logger

logger = get_logger(__name__)


class AnalysisJobManager:
    """Redis-backed state manager for async conversation insights jobs."""

    KEY_PREFIX = "analysis_insights"
    TTL_SECONDS = 60 * 60 * 24

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    def _job_key(self, tenant_id: UUID, job_id: UUID) -> str:
        return f"{self.KEY_PREFIX}:{tenant_id}:{job_id}"

    async def create_job(
        self,
        *,
        job_id: UUID,
        tenant_id: UUID,
        question: str,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
    ) -> AnalysisJob:
        now = datetime.now(timezone.utc)
        job = AnalysisJob(
            job_id=job_id,
            tenant_id=tenant_id,
            status=AnalysisJobStatus.QUEUED,
            question=question,
            assistant_id=assistant_id,
            group_chat_id=group_chat_id,
            created_at=now,
            updated_at=now,
        )
        await self._persist(job)
        return job

    async def get_job(self, *, tenant_id: UUID, job_id: UUID) -> AnalysisJob | None:
        key = self._job_key(tenant_id=tenant_id, job_id=job_id)
        raw = await self.redis.get(key)
        if raw is None:
            return None
        return AnalysisJob.model_validate(orjson.loads(raw))

    async def mark_processing(self, *, tenant_id: UUID, job_id: UUID) -> AnalysisJob | None:
        job = await self.get_job(tenant_id=tenant_id, job_id=job_id)
        if job is None:
            return None
        job.status = AnalysisJobStatus.PROCESSING
        job.updated_at = datetime.now(timezone.utc)
        await self._persist(job)
        return job

    async def mark_completed(
        self, *, tenant_id: UUID, job_id: UUID, answer: str
    ) -> AnalysisJob | None:
        job = await self.get_job(tenant_id=tenant_id, job_id=job_id)
        if job is None:
            return None
        job.status = AnalysisJobStatus.COMPLETED
        job.answer = answer
        job.error = None
        job.updated_at = datetime.now(timezone.utc)
        await self._persist(job)
        return job

    async def mark_failed(
        self, *, tenant_id: UUID, job_id: UUID, error: str
    ) -> AnalysisJob | None:
        job = await self.get_job(tenant_id=tenant_id, job_id=job_id)
        if job is None:
            return None
        job.status = AnalysisJobStatus.FAILED
        job.error = error[:1000]
        job.updated_at = datetime.now(timezone.utc)
        await self._persist(job)
        return job

    async def _persist(self, job: AnalysisJob) -> None:
        key = self._job_key(tenant_id=job.tenant_id, job_id=job.job_id)
        # Keep the key alive at least for one day after the latest update.
        await self.redis.setex(key, timedelta(seconds=self.TTL_SECONDS), orjson.dumps(job.model_dump(mode="json")))
