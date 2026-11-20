from collections.abc import Sequence
from datetime import datetime, timezone
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import TypeAdapter
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql import Executable
from sqlalchemy.sql.base import ExecutableOption

from eneo.apps.app_runs.app_run import AppRun
from eneo.apps.app_runs.app_run_factory import AppRunFactory
from eneo.database.database import AsyncSession
from eneo.database.tables.app_table import AppRuns, AppRunsFiles, Apps
from eneo.database.tables.spaces_table import Spaces
from eneo.files.file_models import FileInfo
from eneo.files.file_repo import FileRepository
from eneo.files.unused_file_cleanup import delete_unused_root_files
from eneo.jobs.job_models import JobFailureCode, JobUpdate
from eneo.jobs.job_repo import JobRepository
from eneo.main.models import Status
from eneo.skills.domain.skill import SkillExecutionReference

_SKILL_PROVENANCE_ADAPTER = TypeAdapter(tuple[SkillExecutionReference, ...])


def _serialize_skill_provenance(
    provenance: tuple[SkillExecutionReference, ...] | None,
) -> list[dict[str, object]] | None:
    if provenance is None:
        return None
    return cast(
        list[dict[str, object]],
        _SKILL_PROVENANCE_ADAPTER.dump_python(provenance, mode="json"),
    )


class AppRunRepository:
    def __init__(
        self,
        session: AsyncSession,
        factory: AppRunFactory,
        file_repo: FileRepository,
    ):
        super().__init__()
        self.session = session
        self.factory = factory
        self.file_repo = file_repo

    def _options(self, stmt: Executable) -> list[ExecutableOption]:
        # Read the status and output in the same PostgreSQL snapshot. DML RETURNING
        # cannot join the job, so write paths load it separately in their transaction.
        job = (
            joinedload(AppRuns.job)
            if isinstance(stmt, sa.Select)
            else selectinload(AppRuns.job)
        )
        return [
            selectinload(AppRuns.user),
            selectinload(AppRuns.input_files),
            job,
        ]

    async def _to_domain(self, app_run: AppRuns) -> AppRun:
        file_ids = [association.file_id for association in app_run.input_files]
        infos = await self.file_repo.get_infos_by_ids(file_ids)
        by_id = {file.id: file for file in infos}
        return self.factory.create_app_run_from_db(
            app_run,
            input_files=[by_id[file_id] for file_id in file_ids if file_id in by_id],
        )

    async def _to_domain_many(self, app_runs: list[AppRuns]) -> list[AppRun]:
        file_ids = list(
            dict.fromkeys(
                association.file_id
                for app_run in app_runs
                for association in app_run.input_files
            )
        )
        infos = await self.file_repo.get_infos_by_ids(file_ids)
        by_id = {file.id: file for file in infos}
        return [
            self.factory.create_app_run_from_db(
                app_run,
                input_files=[
                    by_id[association.file_id]
                    for association in app_run.input_files
                    if association.file_id in by_id
                ],
            )
            for app_run in app_runs
        ]

    async def _get_with_options(
        self, stmt: Executable, multiple: bool = False
    ) -> AppRuns | list[AppRuns] | None:
        for option in self._options(stmt):
            stmt = stmt.options(option)  # type: ignore[union-attr]  # ORM options on DML stmts

        if multiple:
            result = await self.session.scalars(stmt)  # type: ignore[arg-type]  # Executable accepted at runtime
            return list(result.all())  # type: ignore[return-value]

        return await self.session.scalar(stmt)  # type: ignore[arg-type]  # Executable accepted at runtime

    async def _set_input_files(self, app_run_in_db: AppRuns, files: list[FileInfo]):
        values = [dict(app_run_id=app_run_in_db.id, file_id=file.id) for file in files]

        stmt = sa.insert(AppRunsFiles).values(values)
        await self.session.execute(stmt)

        await self.session.refresh(app_run_in_db)

    async def get(self, id: UUID) -> AppRun | None:
        stmt = sa.select(AppRuns).where(AppRuns.id == id)

        app_run_in_db = await self._get_with_options(stmt)

        if app_run_in_db is None:
            return None

        assert isinstance(app_run_in_db, AppRuns)
        return await self._to_domain(app_run_in_db)

    async def get_for_app(self, app_id: UUID, user_id: UUID) -> list[AppRun]:
        stmt = (
            sa.select(AppRuns)
            .where(AppRuns.user_id == user_id)
            .where(AppRuns.app_id == app_id)
            .order_by(AppRuns.created_at.desc())
        )

        app_runs_in_db = cast(
            list[AppRuns],
            await self._get_with_options(stmt, multiple=True),
        )

        return await self._to_domain_many(app_runs_in_db)

    async def get_update_targets_for_jobs(
        self, job_ids: list[UUID]
    ) -> Sequence[tuple[UUID, UUID, UUID, UUID, bool]]:
        stmt = (
            sa.select(
                AppRuns.id,
                AppRuns.user_id,
                AppRuns.app_id,
                Spaces.id,
                Spaces.user_id.is_not(None),
            )
            .join(Apps, Apps.id == AppRuns.app_id)
            .join(Spaces, Spaces.id == Apps.space_id)
            .where(AppRuns.job_id.in_(job_ids))
        )
        return (await self.session.execute(stmt)).tuples().all()

    async def add(self, app_run: AppRun) -> AppRun:
        stmt = (
            sa.insert(AppRuns)
            .values(
                input_text=app_run.input_text,
                output_text=app_run.output,
                num_tokens_input=app_run.num_tokens_input,
                num_tokens_output=app_run.num_tokens_output,
                skill_provenance=_serialize_skill_provenance(app_run.skill_provenance),
                tenant_id=app_run.tenant_id,
                user_id=app_run.user_id,
                app_id=app_run.app_id,
                completion_model_id=app_run.completion_model_id,
            )
            .returning(AppRuns)
        )

        app_run_in_db = await self._get_with_options(stmt)
        assert isinstance(app_run_in_db, AppRuns)

        if app_run.input_files:
            await self._set_input_files(app_run_in_db, app_run.input_files)

        return self.factory.create_app_run_from_db(
            app_run_in_db,
            input_files=app_run.input_files,
        )

    async def update(self, app_run: AppRun) -> AppRun:
        stmt = (
            sa.update(AppRuns)
            .where(AppRuns.id == app_run.id)
            .values(
                job_id=app_run.job_id,
                output_text=app_run.output,
                num_tokens_input=app_run.num_tokens_input,
                num_tokens_output=app_run.num_tokens_output,
                skill_provenance=_serialize_skill_provenance(app_run.skill_provenance),
            )
            .returning(AppRuns)
        )

        app_run_in_db = await self._get_with_options(stmt)
        assert isinstance(app_run_in_db, AppRuns)

        return await self._to_domain(app_run_in_db)

    async def delete(self, id: UUID) -> None:
        """Delete a run and the input Files nothing else uses anymore."""
        file_ids = list(
            await self.session.scalars(
                sa.select(AppRunsFiles.file_id).where(AppRunsFiles.app_run_id == id)
            )
        )
        stmt = sa.delete(AppRuns).where(AppRuns.id == id)
        job_id = await self.session.scalar(stmt.returning(AppRuns.job_id))
        if job_id is not None:
            await JobRepository(self.session).update_job(
                job_id,
                JobUpdate(
                    status=Status.FAILED,
                    failure_code=JobFailureCode.CANCELLED,
                    finished_at=datetime.now(timezone.utc),
                ),
                from_statuses=(Status.QUEUED,),
            )
        await delete_unused_root_files(self.session, file_ids)
