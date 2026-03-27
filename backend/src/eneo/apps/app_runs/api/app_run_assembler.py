from eneo.apps.app_runs.api.app_run_models import (
    AppRunInput,
    AppRunPublic,
    AppRunSparse,
)
from eneo.apps.app_runs.app_run import AppRun
from eneo.files.file_models import FileInfo, FilePublic
from eneo.jobs.job_models import JobInDb


class AppRunAssembler:
    def _to_file_public(self, file: FileInfo):
        return FilePublic(**file.model_dump())

    def _get_job_fields(self, job: JobInDb | None):
        if job:
            return job.finished_at, job.status

        return None, None

    def from_app_run_to_model(self, app_run: AppRun):
        files = [self._to_file_public(file) for file in app_run.input_files]
        finished_at, status = self._get_job_fields(app_run.job)

        return AppRunPublic(
            created_at=app_run.created_at,
            updated_at=app_run.updated_at,
            id=app_run.id,
            input=AppRunInput(
                files=files,
                text=app_run.input_text,
            ),
            output=app_run.output,
            finished_at=finished_at,
            status=status,
            user=app_run.user,
        )

    def from_app_run_to_sparse_model(self, app_run: AppRun):
        files = [self._to_file_public(file) for file in app_run.input_files]
        finished_at, status = self._get_job_fields(app_run.job)

        return AppRunSparse(
            created_at=app_run.created_at,
            updated_at=app_run.updated_at,
            id=app_run.id,
            input=AppRunInput(
                files=files,
                text=app_run.input_text,
            ),
            finished_at=finished_at,
            status=status,
            user=app_run.user,
        )
