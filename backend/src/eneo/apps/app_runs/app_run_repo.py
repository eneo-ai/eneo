from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import defer, selectinload
from sqlalchemy.sql import Executable
from sqlalchemy.sql.base import ExecutableOption

from eneo.apps.app_runs.app_run import AppRun
from eneo.apps.app_runs.app_run_factory import AppRunFactory
from eneo.database.database import AsyncSession
from eneo.database.tables.app_table import AppRuns, AppRunsFiles
from eneo.database.tables.files_table import Files
from eneo.files.file_models import FileInfo


class AppRunRepository:
    def __init__(self, session: AsyncSession, factory: AppRunFactory):
        super().__init__()
        self.session = session
        self.factory = factory

    def _options(self) -> list[ExecutableOption]:
        return [
            selectinload(AppRuns.user),
            selectinload(AppRuns.input_files)
            .selectinload(AppRunsFiles.file)
            .options(defer(Files.blob)),
            selectinload(AppRuns.job),
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
        return self.factory.create_app_run_from_db(app_run_in_db)

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

        return [
            self.factory.create_app_run_from_db(app_run_in_db)
            for app_run_in_db in app_runs_in_db
        ]

    async def add(self, app_run: AppRun) -> AppRun:
        stmt = (
            sa.insert(AppRuns)
            .values(
                input_text=app_run.input_text,
                output_text=app_run.output,
                num_tokens_input=app_run.num_tokens_input,
                num_tokens_output=app_run.num_tokens_output,
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

        return self.factory.create_app_run_from_db(app_run_in_db)

    async def update(self, app_run: AppRun) -> AppRun:
        stmt = (
            sa.update(AppRuns)
            .where(AppRuns.id == app_run.id)
            .values(
                job_id=app_run.job_id,
                output_text=app_run.output,
                num_tokens_input=app_run.num_tokens_input,
                num_tokens_output=app_run.num_tokens_output,
            )
            .returning(AppRuns)
        )

        app_run_in_db = await self._get_with_options(stmt)
        assert isinstance(app_run_in_db, AppRuns)

        return self.factory.create_app_run_from_db(app_run_in_db)

    async def delete(self, id: UUID) -> None:
        stmt = sa.delete(AppRuns).where(AppRuns.id == id)
        await self.session.execute(stmt)
