from datetime import datetime, timezone
from uuid import UUID

from intric.jobs.job_manager import job_manager
from intric.jobs.job_models import Job, JobInDb, JobUpdate, Task
from intric.jobs.job_repo import JobRepository
from intric.jobs.task_models import TaskParams
from intric.main.exceptions import NotFoundException
from intric.main.models import Status
from intric.users.user import UserInDB


class JobService:
    def __init__(
        self,
        user: UserInDB,
        job_repo: JobRepository,
    ):
        self.user = user
        self.job_repo = job_repo

    async def queue_job(
        self, task: Task, *, name: str, task_params: TaskParams
    ) -> JobInDb:
        job = Job(task=task, name=name, status=Status.QUEUED, user_id=self.user.id)
        job_in_db = await self.job_repo.add_job(job=job)

        await job_manager.enqueue(task, job_in_db.id, task_params)

        return job_in_db

    async def set_status(self, job_id: UUID, status: Status):
        job_update = JobUpdate(status=status)

        return await self.job_repo.update_job(job_id, job_update)

    async def complete_job(self, job_id: UUID, result_location: str | None):
        job_update = JobUpdate(
            status=Status.COMPLETE,
            result_location=result_location,
            finished_at=datetime.now(timezone.utc),
        )

        return await self.job_repo.update_job(job_id, job_update)

    async def fail_job(self, job_id: UUID, error_message: str | None = None):
        job_update = JobUpdate(
            status=Status.FAILED,
            finished_at=datetime.now(timezone.utc),
            result_location=error_message,
        )

        return await self.job_repo.update_job(job_id, job_update)

    async def get_running_jobs(self):
        return await self.job_repo.get_running_jobs(self.user.id)

    async def get_job(self, job_id: UUID):
        job = await self.job_repo.get_job(job_id)

        if job is None or job.user_id != self.user.id:
            raise NotFoundException()

        return job
