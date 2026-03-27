from uuid import UUID

from eneo.apps.app_runs.app_run import AppRun
from eneo.apps.apps.app import App
from eneo.database.tables.app_table import AppRuns
from eneo.files.file_models import FileInfo, FilePublic
from eneo.jobs.job_models import JobInDb
from eneo.users.user import UserSparse


class AppRunFactory:
    def create_app_run(
        self,
        app: App,
        files: list[FileInfo],
        text: str | None,
        user_id: UUID,
        tenant_id: UUID,
    ) -> AppRun:
        return AppRun(
            created_at=None,
            updated_at=None,
            id=None,
            job_id=None,
            app_id=app.id,
            user_id=user_id,
            tenant_id=tenant_id,
            input_files=files,
            input_text=text,
            output=None,
            user=None,
            num_tokens_input=None,
            num_tokens_output=None,
            job=None,
            completion_model_id=app.completion_model.id,
        )

    def create_app_run_from_db(self, app_run_in_db: AppRuns):
        input_files = [
            FilePublic.model_validate(input_file.file)
            for input_file in app_run_in_db.input_files
        ]
        user = UserSparse.model_validate(app_run_in_db.user)
        job = (
            JobInDb.model_validate(app_run_in_db.job)
            if app_run_in_db.job is not None
            else None
        )

        return AppRun(
            created_at=app_run_in_db.created_at,
            updated_at=app_run_in_db.updated_at,
            id=app_run_in_db.id,
            job_id=app_run_in_db.job_id,
            app_id=app_run_in_db.app_id,
            user_id=app_run_in_db.user_id,
            tenant_id=app_run_in_db.tenant_id,
            input_files=input_files,
            input_text=app_run_in_db.input_text,
            output=app_run_in_db.output_text,
            user=user,
            num_tokens_input=app_run_in_db.num_tokens_input,
            num_tokens_output=app_run_in_db.num_tokens_output,
            job=job,
            completion_model_id=app_run_in_db.completion_model_id,
        )
