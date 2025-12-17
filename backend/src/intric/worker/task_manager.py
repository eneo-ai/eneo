from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable
from uuid import UUID

from intric.jobs.job_service import JobService
from intric.main.logging import get_logger
from intric.main.models import Channel, ChannelType, RedisMessage, Status
from intric.users.user import UserInDB
from intric.worker.redis import r

logger = get_logger(__name__)


class WorkerConfig:
    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager

    def set_additional_data(self, data: dict):
        self.task_manager.additional_data = data


class TaskManager:
    def __init__(
        self,
        user: UserInDB,
        job_id: UUID,
        job_service: JobService | None = None,
        channel_type: ChannelType | None = None,
        resource_id: UUID | None = None,
    ):
        # job_service is optional for crawl_task which handles its own job status
        # via execute_with_recovery() and sets _job_already_handled=True.
        # All other tasks (upload, transcription) provide job_service via container.
        self.user = user
        self.job_id = job_id
        self.job_service = job_service
        self.channel_type = channel_type
        self.resource_id = resource_id

        self.success = None
        self._result_location = None
        self._cleanup_func = None
        self.additional_data = None
        # Flag for crawl_task to skip complete_job/fail_job (it handles them itself)
        self._job_already_handled = False

    @property
    def result_location(self):
        return self._result_location

    @result_location.setter
    def result_location(self, result_location: str):
        self._result_location = result_location

    @property
    def cleanup_func(self):
        return self._cleanup_func

    @cleanup_func.setter
    def cleanup_func(self, cleanup_func: Callable):
        self._cleanup_func = cleanup_func

    def _log_status(self, status: Status):
        logger.info(f"Status for {self.job_id}: {status}")

    async def _publish_status(self, status: Status):
        if self.channel_type is not None:
            channel = Channel(type=self.channel_type, user_id=self.user.id)
            await r.publish(
                channel.channel_string,
                RedisMessage(
                    id=self.resource_id,
                    status=status,
                    additional_data=self.additional_data,
                ).model_dump_json(),
            )

    @asynccontextmanager
    async def set_status_on_exception(self, *, status_already_set: bool = False):
        """Context manager that handles job status updates and exception handling.

        Args:
            status_already_set: If True, skip the initial IN_PROGRESS status update.
                Used when mark_job_started() has already atomically set the status
                to prevent worker resurrection race condition.
        """
        if not status_already_set:
            await self.set_status(Status.IN_PROGRESS)

        try:
            yield
        except Exception as exc:
            logger.exception("Error on worker:")
            message = str(exc).strip()
            # Avoid storing excessively long error messages on the job record
            truncated_message = message[:512] if message else None
            await self.fail_job(truncated_message)
            self.success = False
        else:
            await self.complete_job()
            self.success = True
        finally:
            if self._cleanup_func is not None:
                self._cleanup_func()

    def successful(self):
        return self.success

    async def set_status(self, status: Status):
        self._log_status(status)
        await self._publish_status(status=status)
        if self.job_service is not None:
            await self.job_service.set_status(self.job_id, status)

    async def complete_job(self):
        if self._job_already_handled:
            return
        await self._publish_status(status=Status.COMPLETE)
        if self.job_service is not None:
            try:
                await self.job_service.complete_job(self.job_id, self._result_location)
            except Exception as exc:
                logger.error(
                    "Failed to mark job as complete",
                    extra={"job_id": str(self.job_id), "error": str(exc)},
                )

    async def fail_job(self, message: str | None = None):
        if self._job_already_handled:
            return
        await self._publish_status(status=Status.FAILED)

        if message:
            logger.warning(
                "Job failed with error",
                extra={"job_id": str(self.job_id), "error_message": message[:512]},
            )

        if self.job_service is not None:
            try:
                await self.job_service.fail_job(self.job_id, message)
            except Exception as exc:
                logger.error(
                    "Failed to mark job as failed",
                    extra={"job_id": str(self.job_id), "error": str(exc)},
                )
