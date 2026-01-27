"""Redis-backed manager for tracking async audit log export jobs."""

from datetime import datetime, timedelta, timezone

import orjson
from typing import Optional
from uuid import UUID

import redis.asyncio as aioredis

from intric.audit.domain.export_job import ExportJob, ExportJobStatus
from intric.main.config import get_settings
from intric.main.logging import get_logger

logger = get_logger(__name__)


class ExportJobManager:
    """Manages export job state in Redis.

    Key pattern: audit_export:{tenant_id}:{job_id}
    TTL: 24 hours (configurable via export_max_age_hours)

    Provides atomic operations for:
    - Job creation and tracking
    - Progress updates
    - Cancellation signaling
    - Concurrency limiting per tenant
    """

    KEY_PREFIX = "audit_export"

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self._settings = get_settings()

    def _job_key(self, tenant_id: UUID, job_id: UUID) -> str:
        """Generate Redis key for a job."""
        return f"{self.KEY_PREFIX}:{tenant_id}:{job_id}"

    def _tenant_jobs_pattern(self, tenant_id: UUID) -> str:
        """Generate pattern to match all jobs for a tenant."""
        return f"{self.KEY_PREFIX}:{tenant_id}:*"

    def _calculate_ttl_seconds(self) -> int:
        """Calculate TTL in seconds from config."""
        return self._settings.export_max_age_hours * 3600

    async def create_job(
        self,
        job_id: UUID,
        tenant_id: UUID,
        format: str = "csv",
    ) -> ExportJob:
        """Create a new export job in pending state.

        Args:
            job_id: Unique job identifier
            tenant_id: Tenant for multi-tenant isolation
            format: Export format (csv or jsonl)

        Returns:
            Created ExportJob instance
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=self._settings.export_max_age_hours)

        job = ExportJob(
            job_id=job_id,
            tenant_id=tenant_id,
            status=ExportJobStatus.PENDING,
            format=format,
            created_at=now,
            expires_at=expires_at,
        )

        key = self._job_key(tenant_id, job_id)
        ttl = self._calculate_ttl_seconds()

        await self.redis.setex(
            key,
            ttl,
            orjson.dumps(job.to_redis_dict()),
        )

        logger.info(
            "Created export job",
            extra={
                "job_id": str(job_id),
                "tenant_id": str(tenant_id),
                "format": format,
            },
        )

        return job

    async def get_job(self, tenant_id: UUID, job_id: UUID) -> Optional[ExportJob]:
        """Get job status by ID.

        Args:
            tenant_id: Tenant ID (for key construction and validation)
            job_id: Job ID to retrieve

        Returns:
            ExportJob if found, None otherwise
        """
        key = self._job_key(tenant_id, job_id)
        data = await self.redis.get(key)

        if not data:
            return None

        return ExportJob.from_redis_dict(orjson.loads(data))

    async def update_progress(
        self,
        tenant_id: UUID,
        job_id: UUID,
        processed_records: int,
        total_records: int,
    ) -> Optional[ExportJob]:
        """Update job progress.

        Called periodically by the worker (every export_progress_interval records).

        Args:
            tenant_id: Tenant ID
            job_id: Job ID
            processed_records: Number of records processed so far
            total_records: Total records to process

        Returns:
            Updated ExportJob if found, None otherwise
        """
        job = await self.get_job(tenant_id, job_id)
        if not job:
            return None

        job.processed_records = processed_records
        job.total_records = total_records

        # Calculate progress percentage
        if total_records > 0:
            job.progress = min(99, int((processed_records / total_records) * 100))
        else:
            job.progress = 0

        # Ensure job is in PROCESSING state
        if job.status == ExportJobStatus.PENDING:
            job.status = ExportJobStatus.PROCESSING
            job.started_at = datetime.now(timezone.utc)

        key = self._job_key(tenant_id, job_id)
        ttl = self._calculate_ttl_seconds()

        await self.redis.setex(
            key,
            ttl,
            orjson.dumps(job.to_redis_dict()),
        )

        return job

    async def mark_processing(
        self,
        tenant_id: UUID,
        job_id: UUID,
    ) -> Optional[ExportJob]:
        """Mark job as processing (started).

        Args:
            tenant_id: Tenant ID
            job_id: Job ID

        Returns:
            Updated ExportJob if found, None otherwise
        """
        job = await self.get_job(tenant_id, job_id)
        if not job:
            return None

        job.status = ExportJobStatus.PROCESSING
        job.started_at = datetime.now(timezone.utc)

        key = self._job_key(tenant_id, job_id)
        ttl = self._calculate_ttl_seconds()

        await self.redis.setex(
            key,
            ttl,
            orjson.dumps(job.to_redis_dict()),
        )

        logger.info(
            "Export job started processing",
            extra={
                "job_id": str(job_id),
                "tenant_id": str(tenant_id),
            },
        )

        return job

    async def complete_job(
        self,
        tenant_id: UUID,
        job_id: UUID,
        file_path: str,
        file_size_bytes: int,
        total_records: int,
    ) -> Optional[ExportJob]:
        """Mark job as completed with file info.

        Args:
            tenant_id: Tenant ID
            job_id: Job ID
            file_path: Path to generated export file
            file_size_bytes: Size of the file in bytes
            total_records: Total records exported

        Returns:
            Updated ExportJob if found, None otherwise
        """
        job = await self.get_job(tenant_id, job_id)
        if not job:
            return None

        job.status = ExportJobStatus.COMPLETED
        job.progress = 100
        job.processed_records = total_records
        job.total_records = total_records
        job.file_path = file_path
        job.file_size_bytes = file_size_bytes
        job.completed_at = datetime.now(timezone.utc)

        key = self._job_key(tenant_id, job_id)
        ttl = self._calculate_ttl_seconds()

        await self.redis.setex(
            key,
            ttl,
            orjson.dumps(job.to_redis_dict()),
        )

        logger.info(
            "Export job completed",
            extra={
                "job_id": str(job_id),
                "tenant_id": str(tenant_id),
                "file_path": file_path,
                "file_size_bytes": file_size_bytes,
                "total_records": total_records,
            },
        )

        return job

    async def fail_job(
        self,
        tenant_id: UUID,
        job_id: UUID,
        error_message: str,
    ) -> Optional[ExportJob]:
        """Mark job as failed with error details.

        Args:
            tenant_id: Tenant ID
            job_id: Job ID
            error_message: Error description

        Returns:
            Updated ExportJob if found, None otherwise
        """
        job = await self.get_job(tenant_id, job_id)
        if not job:
            return None

        job.status = ExportJobStatus.FAILED
        job.error_message = error_message
        job.completed_at = datetime.now(timezone.utc)

        key = self._job_key(tenant_id, job_id)
        ttl = self._calculate_ttl_seconds()

        await self.redis.setex(
            key,
            ttl,
            orjson.dumps(job.to_redis_dict()),
        )

        logger.error(
            "Export job failed",
            extra={
                "job_id": str(job_id),
                "tenant_id": str(tenant_id),
                "error_message": error_message,
            },
        )

        return job

    async def set_cancelled(
        self,
        tenant_id: UUID,
        job_id: UUID,
    ) -> bool:
        """Signal a job to be cancelled.

        Sets the cancelled flag which the worker checks periodically.
        The worker will then stop processing and mark the job as CANCELLED.

        Args:
            tenant_id: Tenant ID
            job_id: Job ID

        Returns:
            True if job was found and can be cancelled, False otherwise
        """
        job = await self.get_job(tenant_id, job_id)
        if not job:
            return False

        if not job.can_be_cancelled():
            return False

        job.cancelled = True

        key = self._job_key(tenant_id, job_id)
        ttl = self._calculate_ttl_seconds()

        await self.redis.setex(
            key,
            ttl,
            orjson.dumps(job.to_redis_dict()),
        )

        logger.info(
            "Export job cancellation requested",
            extra={
                "job_id": str(job_id),
                "tenant_id": str(tenant_id),
            },
        )

        return True

    async def mark_cancelled(
        self,
        tenant_id: UUID,
        job_id: UUID,
    ) -> Optional[ExportJob]:
        """Mark job as cancelled (called by worker when it stops).

        Args:
            tenant_id: Tenant ID
            job_id: Job ID

        Returns:
            Updated ExportJob if found, None otherwise
        """
        job = await self.get_job(tenant_id, job_id)
        if not job:
            return None

        job.status = ExportJobStatus.CANCELLED
        job.completed_at = datetime.now(timezone.utc)

        key = self._job_key(tenant_id, job_id)
        ttl = self._calculate_ttl_seconds()

        await self.redis.setex(
            key,
            ttl,
            orjson.dumps(job.to_redis_dict()),
        )

        logger.info(
            "Export job cancelled",
            extra={
                "job_id": str(job_id),
                "tenant_id": str(tenant_id),
            },
        )

        return job

    async def is_cancelled(
        self,
        tenant_id: UUID,
        job_id: UUID,
    ) -> bool:
        """Check if a job has been marked for cancellation.

        Called by the worker periodically during processing.

        Args:
            tenant_id: Tenant ID
            job_id: Job ID

        Returns:
            True if job should be cancelled, False otherwise
        """
        job = await self.get_job(tenant_id, job_id)
        if not job:
            return True  # Job not found, treat as cancelled

        return job.cancelled

    async def count_active_jobs(self, tenant_id: UUID) -> int:
        """Count active (non-terminal) export jobs for a tenant.

        Used for concurrency limiting.

        Args:
            tenant_id: Tenant ID

        Returns:
            Number of pending or processing jobs
        """
        pattern = self._tenant_jobs_pattern(tenant_id)
        cursor = 0
        active_count = 0

        while True:
            cursor, keys = await self.redis.scan(
                cursor=cursor,
                match=pattern,
                count=100,
            )

            for key in keys:
                data = await self.redis.get(key)
                if data:
                    job = ExportJob.from_redis_dict(orjson.loads(data))
                    if not job.is_terminal():
                        active_count += 1

            if cursor == 0:
                break

        return active_count

    async def delete_job(self, tenant_id: UUID, job_id: UUID) -> bool:
        """Delete a job from Redis.

        Used during cleanup of old jobs.

        Args:
            tenant_id: Tenant ID
            job_id: Job ID

        Returns:
            True if job was deleted, False if not found
        """
        key = self._job_key(tenant_id, job_id)
        result = await self.redis.delete(key)
        return result > 0

    async def get_expired_jobs(self) -> list[ExportJob]:
        """Get all expired jobs across all tenants.

        Used by the cleanup cron job.

        Returns:
            List of expired ExportJob instances
        """
        pattern = f"{self.KEY_PREFIX}:*"
        cursor = 0
        expired_jobs = []
        now = datetime.now(timezone.utc)

        while True:
            cursor, keys = await self.redis.scan(
                cursor=cursor,
                match=pattern,
                count=100,
            )

            for key in keys:
                data = await self.redis.get(key)
                if data:
                    job = ExportJob.from_redis_dict(orjson.loads(data))
                    if job.expires_at <= now:
                        expired_jobs.append(job)

            if cursor == 0:
                break

        return expired_jobs
