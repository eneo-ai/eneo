from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from intric.apps.apps.api.app_models import InputField
from intric.apps.apps.app import App
from intric.apps.apps.app_factory import AppFactory
from intric.database.database import AsyncSession
from intric.database.tables.app_table import Apps, AppsFiles, AppsPrompts, InputFields
from intric.files.file_models import FileInfo
from intric.prompts.prompt import Prompt
from intric.prompts.prompt_repo import PromptRepository
from intric.transcription_models.domain.transcription_model_repo import (
    TranscriptionModelRepository,
)


class AppRepository:
    def __init__(
        self,
        session: AsyncSession,
        factory: AppFactory,
        prompt_repo: PromptRepository,
        transcription_model_repo: TranscriptionModelRepository,
    ):
        self.session = session
        self.factory = factory
        self.prompt_repo = prompt_repo
        self.transcription_model_repo = transcription_model_repo

    def _options(self):
        return [
            selectinload(Apps.completion_model),
            selectinload(Apps.input_fields),
            selectinload(Apps.attachments).selectinload(AppsFiles.file),
            selectinload(Apps.template),
        ]

    async def _get_record_with_options(self, stmt):
        for option in self._options():
            stmt = stmt.options(option)

        return await self.session.scalar(stmt)

    async def _get_selected_prompt(self, app_id: UUID):
        stmt = (
            sa.select(AppsPrompts.prompt_id)
            .where(AppsPrompts.app_id == app_id)
            .where(AppsPrompts.is_selected)
        )

        prompt_id = await self.session.scalar(stmt)

        return await self.prompt_repo.get(prompt_id)

    async def _set_input_fields(self, app_in_db: Apps, input_fields: list[InputField]):
        # Delete all
        stmt = sa.delete(InputFields).where(InputFields.app_id == app_in_db.id)
        await self.session.execute(stmt)

        # Add input_fields
        if input_fields:
            input_fields_dict = [
                dict(
                    type=input_field.type,
                    description=input_field.description,
                    app_id=app_in_db.id,
                    tenant_id=app_in_db.tenant_id,
                    user_id=app_in_db.user_id,
                )
                for input_field in input_fields
            ]

            stmt = sa.insert(InputFields).values(input_fields_dict)
            await self.session.execute(stmt)

        # This allows the newly added input fields to be reflected in the app
        await self.session.refresh(app_in_db)

    async def _set_prompt(self, app_in_db: Apps, prompt: Prompt):
        # Set all other prompts for this app as not selected
        stmt = (
            sa.update(AppsPrompts)
            .where(AppsPrompts.app_id == app_in_db.id)
            .values(is_selected=False)
        )
        await self.session.execute(stmt)

        # Upsert to the apps_prompts table
        stmt = (
            insert(AppsPrompts)
            .values(
                prompt_id=prompt.id,
                app_id=app_in_db.id,
                is_selected=True,
            )
            .on_conflict_do_update(
                constraint="build_a_services_prompts_pkey",
                set_=dict(is_selected=True),
            )
        )

        await self.session.execute(stmt)

    async def _set_attachments(self, app_in_db: App, attachments: list[FileInfo]):
        # Delete all
        stmt = sa.delete(AppsFiles).where(AppsFiles.app_id == app_in_db.id)
        await self.session.execute(stmt)

        # Add attachments
        if attachments:
            attachments_dicts = [dict(app_id=app_in_db.id, file_id=file.id) for file in attachments]

            stmt = sa.insert(AppsFiles).values(attachments_dicts)
            await self.session.execute(stmt)

        await self.session.refresh(app_in_db)

    async def add(self, app: App) -> App:
        model_kwargs = (
            None
            if app.completion_model_kwargs is None
            else app.completion_model_kwargs.model_dump()
        )

        transcription_model_id = (
            None if app.transcription_model is None else app.transcription_model.id
        )

        template_id = app.source_template.id if app.source_template else None
        stmt = (
            sa.insert(Apps)
            .values(
                name=app.name,
                description=app.description,
                completion_model_kwargs=model_kwargs,
                tenant_id=app.tenant_id,
                user_id=app.user_id,
                space_id=app.space_id,
                completion_model_id=app.completion_model.id,
                published=app.published,
                template_id=template_id,
                transcription_model_id=transcription_model_id,
            )
            .returning(Apps)
        )

        entry_in_db = await self._get_record_with_options(stmt)

        if app.prompt is not None:
            await self._set_prompt(entry_in_db, app.prompt)

        await self._set_input_fields(entry_in_db, app.input_fields)
        await self._set_attachments(entry_in_db, app.attachments)

        return self.factory.create_app_from_db(
            entry_in_db, prompt=app.prompt, transcription_model=app.transcription_model
        )

    async def get(self, id: UUID) -> App:
        stmt = sa.select(Apps).where(Apps.id == id)

        entry_in_db = await self._get_record_with_options(stmt)

        if entry_in_db is None:
            return

        prompt = await self._get_selected_prompt(app_id=id)

        # Get transcription model using the repo
        transcription_model = None
        if entry_in_db.transcription_model_id:
            transcription_model = await self.transcription_model_repo.one(
                entry_in_db.transcription_model_id
            )

        return self.factory.create_app_from_db(
            entry_in_db, prompt=prompt, transcription_model=transcription_model
        )

    async def update(self, app: App) -> App:
        model_kwargs = (
            None
            if app.completion_model_kwargs is None
            else app.completion_model_kwargs.model_dump()
        )

        transcription_model_id = (
            None if app.transcription_model is None else app.transcription_model.id
        )

        stmt = (
            sa.update(Apps)
            .values(
                name=app.name,
                description=app.description,
                completion_model_kwargs=model_kwargs,
                tenant_id=app.tenant_id,
                user_id=app.user_id,
                space_id=app.space_id,
                completion_model_id=app.completion_model.id,
                transcription_model_id=transcription_model_id,
                published=app.published,
                data_retention_days=app.data_retention_days,
                icon_id=app.icon_id,
            )
            .where(Apps.id == app.id)
            .returning(Apps)
        )

        entry_in_db = await self._get_record_with_options(stmt)

        if app.prompt is not None:
            await self._set_prompt(entry_in_db, app.prompt)

        await self._set_input_fields(entry_in_db, app.input_fields)
        await self._set_attachments(entry_in_db, app.attachments)

        return self.factory.create_app_from_db(
            entry_in_db, prompt=app.prompt, transcription_model=app.transcription_model
        )

    async def delete(self, id: UUID):
        stmt = sa.delete(Apps).where(Apps.id == id)
        await self.session.execute(stmt)

    async def get_by_space(self, space_id: UUID):
        stmt = sa.select(Apps).where(Apps.space_id == space_id).order_by(Apps.created_at)

        for option in self._options():
            stmt = stmt.options(option)

        records = await self.session.scalars(stmt)

        apps = []
        for record in records:
            prompt = await self._get_selected_prompt(record.id)

            # Get transcription model using the repo
            transcription_model = None
            if record.transcription_model_id:
                transcription_model = await self.transcription_model_repo.one(
                    record.transcription_model_id
                )

            app = self.factory.create_app_from_db(
                app_in_db=record, prompt=prompt, transcription_model=transcription_model
            )
            apps.append(app)

        return apps
