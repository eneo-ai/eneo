from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import defer, selectinload

from intric.apps.app_runs.app_run import AppRun
from intric.apps.app_runs.app_run_factory import AppRunFactory
from intric.database.database import AsyncSession
from intric.database.tables.app_table import AppRuns, AppRunsFiles
from intric.database.tables.files_table import Files
from intric.files.file_models import FileInfo


class AppRunRepository:
    def __init__(self, session: AsyncSession, factory: AppRunFactory):
        self.session = session
        self.factory = factory

    def _options(self):
        return [
            selectinload(AppRuns.user),
            selectinload(AppRuns.input_files)
            .selectinload(AppRunsFiles.file)
            .options(defer(Files.blob)),
            selectinload(AppRuns.job),
        ]

    async def _get_with_options(self, stmt, multiple=False):
        for option in self._options():
            stmt = stmt.options(option)

        if multiple:
            return await self.session.scalars(stmt)

        return await self.session.scalar(stmt)

    async def _set_input_files(self, app_run_in_db: AppRuns, files: list[FileInfo]):
        values = [dict(app_run_id=app_run_in_db.id, file_id=file.id) for file in files]

        stmt = sa.insert(AppRunsFiles).values(values)
        await self.session.execute(stmt)

        await self.session.refresh(app_run_in_db)

    async def get(self, id: UUID):
        stmt = sa.select(AppRuns).where(AppRuns.id == id)

        app_run_in_db = await self._get_with_options(stmt)

        if app_run_in_db is None:
            return

        return self.factory.create_app_run_from_db(app_run_in_db)

    async def get_for_app(self, app_id: UUID, user_id: UUID):
        stmt = (
            sa.select(AppRuns)
            .where(AppRuns.user_id == user_id)
            .where(AppRuns.app_id == app_id)
            .order_by(AppRuns.created_at.desc())
        )

        app_runs_in_db = await self._get_with_options(stmt, multiple=True)
        assert app_runs_in_db is not None

        return [
            self.factory.create_app_run_from_db(app_run_in_db)
            for app_run_in_db in app_runs_in_db
        ]

    async def add(self, app_run: AppRun):
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

        if app_run.input_files:
            await self._set_input_files(app_run_in_db, app_run.input_files)

        return self.factory.create_app_run_from_db(app_run_in_db)

    async def update(self, app_run: AppRun):
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

        return self.factory.create_app_run_from_db(app_run_in_db)

    async def delete(self, id: UUID):
        stmt = sa.delete(AppRuns).where(AppRuns.id == id)
        await self.session.execute(stmt)
