from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable
from uuid import UUID

from intric.database.database import AsyncSession
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
        session: AsyncSession,
        job_service: JobService,
        channel_type: ChannelType | None = None,
        resource_id: UUID | None = None,
    ):
        self.user = user
        self.job_id = job_id
        self.session = session
        self.job_service = job_service
        self.channel_type = channel_type
        self.resource_id = resource_id

        self.success = None
        self._result_location = None
        self._cleanup_func = None

        self.additional_data = None

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
    async def set_status_on_exception(self):
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
        await self.job_service.set_status(self.job_id, status)

    async def complete_job(self):
        await self._publish_status(status=Status.COMPLETE)
        await self.job_service.complete_job(self.job_id, self.result_location)

    async def fail_job(self, message: str | None = None):
        await self._publish_status(status=Status.FAILED)
        await self.job_service.fail_job(self.job_id, message)
