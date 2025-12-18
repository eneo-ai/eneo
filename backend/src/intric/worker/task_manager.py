from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

import sqlalchemy as sa

from intric.database.database import sessionmanager
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
        job_service: JobService | None = None,
        channel_type: ChannelType | None = None,
        resource_id: UUID | None = None,
    ):
        # NOTE: job_service is now optional for long-running worker tasks.
        # Why: The "sessionless container" pattern for crawl_task cannot provide
        # job_service because it triggers a transitive dependency chain:
        #   task_manager → job_service → job_repo → session
        # This fails type validation when session=None.
        #
        # In crawl_task, job_service is NOT needed because:
        # 1. _job_already_handled=True skips complete_job/fail_job
        # 2. Status updates use execute_with_recovery() with own sessions
        # 3. set_status() is never called in the crawl path
        #
        # For non-crawl tasks (using @worker.task decorator), job_service
        # is still provided via container.task_manager().
        self.user = user
        self.job_id = job_id
        self.job_service = job_service
        self.channel_type = channel_type
        self.resource_id = resource_id

        self.success = None
        self._result_location = None
        self._cleanup_func = None
        # Flag to skip job completion if already handled by crawl_task
        # Why: crawl_task uses execute_with_recovery() to handle job completion
        # with its own session management. This flag prevents duplicate updates.
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
    async def set_status_on_exception(self, *, status_already_set: bool = False):
        """Context manager that handles job status updates and exception handling.

        Args:
            status_already_set: If True, skip the initial IN_PROGRESS status update.
                Used when mark_job_started() has already atomically set the status
                to prevent worker resurrection race condition.
        """
        import asyncio

        if not status_already_set:
            await self.set_status(Status.IN_PROGRESS)

        try:
            yield
        except asyncio.CancelledError:
            # CancelledError inherits from BaseException (not Exception) in Python 3.8+
            # Must handle explicitly to mark job as failed when worker shuts down
            logger.warning(
                "Job cancelled (worker shutdown or timeout)",
                extra={"job_id": str(self.job_id)},
            )
            await self.fail_job("Job cancelled")
            self.success = False
            raise  # Re-raise to let ARQ know the job was cancelled
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

        # ALWAYS use fresh session to avoid deadlock with task session.
        # Why: The task session holds a transaction open. If we update job status
        # via task session (job_service.set_status), then complete_job() tries to
        # update the same row with a fresh session, causing a deadlock:
        # - Fresh session waits for task session to release row lock
        # - Task session waits for complete_job() to return before committing
        # Using fresh sessions for ALL job status updates avoids this.
        try:
            async with sessionmanager.session() as session, session.begin():
                stmt = (
                    sa.update(Jobs)
                    .where(Jobs.id == self.job_id)
                    .values(status=status.value)
                )
                await session.execute(stmt)
        except Exception as exc:
            logger.warning(
                "Failed to update job status in database",
                extra={"job_id": str(self.job_id), "status": status.value, "error": str(exc)},
            )

    async def complete_job(self):
        if self._job_already_handled:
            # Job was already completed by crawl_task using execute_with_recovery()
            # Skip to avoid duplicate status update
            return
        await self._publish_status(status=Status.COMPLETE)

        # Use fresh session to avoid deadlock with task session
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
            # Job was already failed by crawl_task using execute_with_recovery()
            # Skip to avoid duplicate status update
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
