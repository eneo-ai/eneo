from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

import sqlalchemy as sa

from intric.database.database import AsyncSession, sessionmanager
from intric.database.tables.job_table import Jobs
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
        # Flag to skip job completion if already handled by crawl_task
        # Why: After session recovery, this TaskManager holds stale session references.
        # crawl_task handles completion using current_session(), then sets this flag
        # so we don't attempt to use the stale job_service.
        self._job_already_handled = False

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
        if self._job_already_handled:
            # Job was already completed by crawl_task using current_session()
            # Skip to avoid "closed transaction" error from stale session
            return
        await self._publish_status(status=Status.COMPLETE)

        # FIX: Use fresh session instead of potentially stale self.job_service
        # Why: Consistency with fail_job() - always use fresh session for job status updates
        try:
            async with sessionmanager.session() as session, session.begin():
                stmt = (
                    sa.update(Jobs)
                    .where(Jobs.id == self.job_id)
                    .values(
                        status=Status.COMPLETE.value,
                        finished_at=datetime.now(timezone.utc),
                        result_location=self._result_location,
                    )
                )
                await session.execute(stmt)
        except Exception as exc:
            logger.error(
                "Failed to mark job as complete in database",
                extra={"job_id": str(self.job_id), "error": str(exc)},
            )

    async def fail_job(self, message: str | None = None):
        if self._job_already_handled:
            # Job was already failed by crawl_task using current_session()
            # Skip to avoid "closed transaction" error from stale session
            return
        await self._publish_status(status=Status.FAILED)

        # FIX: Use fresh session instead of potentially stale self.job_service
        # Why: After session recovery or transaction errors, the injected job_service
        # holds a reference to a stale/closed session. Using sessionmanager.session()
        # ensures we always have a working session for this critical operation.
        # NOTE: Jobs table doesn't have error_message column - message is logged only
        if message:
            logger.warning(
                "Job failed with error",
                extra={"job_id": str(self.job_id), "error_message": message[:512]},
            )
        try:
            async with sessionmanager.session() as session, session.begin():
                stmt = (
                    sa.update(Jobs)
                    .where(Jobs.id == self.job_id)
                    .values(
                        status=Status.FAILED.value,
                        finished_at=datetime.now(timezone.utc),
                    )
                )
                await session.execute(stmt)
        except Exception as exc:
            # Log but don't raise - we've already published the failure status
            # The job will be caught by Safe Watchdog if DB update fails
            logger.error(
                "Failed to mark job as failed in database",
                extra={"job_id": str(self.job_id), "error": str(exc)},
            )
