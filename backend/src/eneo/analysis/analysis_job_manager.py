from datetime import datetime, timedelta, timezone
from uuid import UUID

import orjson
import redis.asyncio as aioredis

from eneo.analysis.analysis import AnalysisJobStatus
from eneo.analysis.analysis_job import AnalysisJob
from eneo.main.logging import get_logger

logger = get_logger(__name__)


class AnalysisJobManager:
    """Redis-backed state manager for async conversation insights jobs."""

    KEY_PREFIX = "analysis_insights"
    TTL_SECONDS = 60 * 60 * 24

    def __init__(self, redis: aioredis.Redis) -> None:
        super().__init__()
        self.redis = redis

    def _job_key(self, tenant_id: UUID, job_id: UUID) -> str:
        return f"{self.KEY_PREFIX}:{tenant_id}:{job_id}"

    async def create_job(
        self,
        *,
        job_id: UUID,
        tenant_id: UUID,
        question: str,
        assistant_id: UUID,
    ) -> AnalysisJob:
        now = datetime.now(timezone.utc)
        job = AnalysisJob(
            job_id=job_id,
            tenant_id=tenant_id,
            status=AnalysisJobStatus.QUEUED,
            question=question,
            assistant_id=assistant_id,
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
        record: dict[str, object] = orjson.loads(raw)
        # Until pre-upgrade Redis jobs expire, a group ID can be the only
        # target. Retirement preserved that UUID on the migrated assistant.
        group_chat_id = record.pop("group_chat_id", None)
        if (record.get("assistant_id") is None) == (group_chat_id is None):
            return None
        if group_chat_id is not None:
            record["assistant_id"] = group_chat_id
        return AnalysisJob.model_validate(record)

    async def mark_processing(
        self, *, tenant_id: UUID, job_id: UUID
    ) -> AnalysisJob | None:
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
        await self.redis.setex(
            key,
            timedelta(seconds=self.TTL_SECONDS),
            orjson.dumps(job.model_dump(mode="json")),
        )
