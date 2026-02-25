from uuid import UUID

from intric.apps.app_runs.api.app_run_models import AppRunParams
from intric.apps.app_runs.app_run_factory import AppRunFactory
from intric.apps.app_runs.app_run_repo import AppRunRepository
from intric.apps.apps.app_service import AppService
from intric.completion_models.infrastructure.context_builder import count_tokens
from intric.files.file_service import FileService
from intric.jobs.job_models import Task
from intric.jobs.job_service import JobService
from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from intric.users.user import UserInDB


class AppRunService:
    def __init__(
        self,
        user: UserInDB,
        repo: AppRunRepository,
        factory: AppRunFactory,
        app_service: AppService,
        job_service: JobService,
        file_service: FileService,
    ):
        self.user = user
        self.repo = repo
        self.factory = factory
        self.app_service = app_service
        self.job_service = job_service
        self.file_service = file_service

    async def queue_app_run(self, app_id: UUID, file_ids: list[UUID], text: str | None):
        app, _ = await self.app_service.get_app(app_id)

        files = await self.file_service.get_file_infos(file_ids)

        if not app.is_valid_input(files, text=text):
            raise BadRequestException()

        app_run = self.factory.create_app_run(
            app=app,
            files=files,
            text=text,
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
        )

        app_run_in_db = await self.repo.add(app_run)

        job = await self.job_service.queue_job(
            Task.RUN_APP,
            name=app.name,
            task_params=AppRunParams(
                id=app_run_in_db.id,
                user_id=self.user.id,
                file_ids=file_ids,
                text=text,
                app_id=app.id,
            ),
        )

        app_run_in_db.update(job_id=job.id)

        return await self.repo.update(app_run_in_db)

    async def get_app_run(self, id: UUID):
        app_run = await self.repo.get(id)

        if app_run is None:
            raise NotFoundException()

        if app_run.user_id != self.user.id:
            raise UnauthorizedException(
                "You do not have permission to read this app run.",
                code="forbidden_action",
                context={
                    "resource_type": "app_run",
                    "action": "read",
                    "auth_layer": "domain_policy",
                },
            )

        return app_run

    async def get_app_runs(self, app_id: UUID):
        # Check that we can access the app
        await self.app_service.get_app(app_id)

        return await self.repo.get_for_app(app_id=app_id, user_id=self.user.id)

    async def delete_app_run(self, id: UUID):
        # Check that we can access the run
        # TODO: If the conditions for accessing change,
        # we should review how we delete the runs
        await self.get_app_run(id)

        await self.repo.delete(id)

    async def run_app(
        self, app_id: UUID, app_run_id: UUID, file_ids: list[UUID], text: str | None
    ):
        app_run = await self.get_app_run(app_run_id)

        response = await self.app_service.run_app(app_id, file_ids=file_ids, text=text)

        # Count the output tokens
        total_output_tokens = count_tokens(response.completion.text)

        app_run.update(
            output=response.completion.text,
            num_tokens_input=response.total_token_count,
            num_tokens_output=total_output_tokens,
        )

        await self.repo.update(app_run)
