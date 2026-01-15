"""Audit log export worker task."""

import os
from uuid import UUID

import redis.asyncio as aioredis

from intric.audit.application.audit_export_service import AuditExportService
from intric.audit.application.audit_task_params import AuditExportTaskParams
from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from intric.audit.infrastructure.export_job_manager import ExportJobManager
from intric.database.database import AsyncSession
from intric.main.config import get_settings
from intric.main.logging import get_logger

logger = get_logger(__name__)


async def export_audit_logs_task(
    job_id: str,
    params: dict,
    session: AsyncSession,
    redis: aioredis.Redis,
) -> dict:
    """
    Worker task to export audit logs to file.

    Uses streaming for constant memory usage regardless of dataset size.
    Updates progress in Redis every 5000 records (configurable).
    Supports cancellation via Redis flag.

    Args:
        job_id: ARQ job ID (also used as export job ID)
        params: Export parameters (validated into AuditExportTaskParams)
        session: Database session
        redis: Redis client for job tracking

    Returns:
        Dictionary with export result
    """
    settings = get_settings()
    job_manager = ExportJobManager(redis)
    job_uuid = UUID(job_id)

    # Validate params
    task_params = AuditExportTaskParams.from_dict(params)

    # Create export directory for tenant
    export_dir = settings.export_dir / str(task_params.tenant_id)
    export_dir.mkdir(parents=True, exist_ok=True)

    # Determine file extension
    extension = "csv" if task_params.format.value == "csv" else "jsonl"
    file_path = export_dir / f"{job_id}.{extension}"

    logger.info(
        "Starting export job",
        extra={
            "job_id": job_id,
            "tenant_id": str(task_params.tenant_id),
            "format": task_params.format.value,
            "file_path": str(file_path),
        },
    )

    # Mark job as processing
    await job_manager.mark_processing(task_params.tenant_id, job_uuid)

    # Create export service with repository
    repository = AuditLogRepositoryImpl(session)
    service = AuditExportService(repository=repository)

    # Define progress callback
    async def progress_callback(processed: int, total: int) -> None:
        await job_manager.update_progress(
            tenant_id=task_params.tenant_id,
            job_id=job_uuid,
            processed_records=processed,
            total_records=total,
        )

    # Define cancellation check
    async def cancellation_check() -> bool:
        return await job_manager.is_cancelled(task_params.tenant_id, job_uuid)

    try:
        # Stream export to file
        total_records = await service.stream_export_to_file(
            file_path=str(file_path),
            tenant_id=task_params.tenant_id,
            format=task_params.format.value,
            progress_callback=progress_callback,
            cancellation_check=cancellation_check,
            user_id=task_params.user_id,
            actor_id=task_params.actor_id,
            action=task_params.action,
            from_date=task_params.from_date,
            to_date=task_params.to_date,
            max_records=task_params.max_records,
        )

        # Check if cancelled during processing
        if await job_manager.is_cancelled(task_params.tenant_id, job_uuid):
            await job_manager.mark_cancelled(task_params.tenant_id, job_uuid)
            # Clean up partial file
            if file_path.exists():
                os.remove(file_path)
            return {
                "job_id": job_id,
                "status": "cancelled",
                "processed_records": total_records,
            }

        # Get file size
        file_size = file_path.stat().st_size

        # Mark job as completed
        await job_manager.complete_job(
            tenant_id=task_params.tenant_id,
            job_id=job_uuid,
            file_path=str(file_path),
            file_size_bytes=file_size,
            total_records=total_records,
        )

        return {
            "job_id": job_id,
            "status": "completed",
            "file_path": str(file_path),
            "file_size_bytes": file_size,
            "total_records": total_records,
        }

    except Exception as e:
        error_message = str(e)
        logger.exception(
            "Export job failed",
            extra={
                "job_id": job_id,
                "tenant_id": str(task_params.tenant_id),
                "error": error_message,
            },
        )

        # Mark job as failed
        await job_manager.fail_job(
            tenant_id=task_params.tenant_id,
            job_id=job_uuid,
            error_message=error_message,
        )

        # Clean up partial file
        if file_path.exists():
            os.remove(file_path)

        return {
            "job_id": job_id,
            "status": "failed",
            "error_message": error_message,
        }
