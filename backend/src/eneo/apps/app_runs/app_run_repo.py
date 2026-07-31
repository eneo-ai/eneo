from typing import cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import TypeAdapter
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Executable
from sqlalchemy.sql.base import ExecutableOption

from eneo.apps.app_runs.app_run import AppRun
from eneo.apps.app_runs.app_run_factory import AppRunFactory
from eneo.database.database import AsyncSession
from eneo.database.tables.app_table import AppRuns, AppRunsFiles
from eneo.files.file_models import FileInfo
from eneo.files.file_repo import FileRepository
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

    def _options(self) -> list[ExecutableOption]:
        return [
            selectinload(AppRuns.user),
            selectinload(AppRuns.input_files),
            selectinload(AppRuns.job),
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
        for option in self._options():
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
        stmt = sa.delete(AppRuns).where(AppRuns.id == id)
        await self.session.execute(stmt)
