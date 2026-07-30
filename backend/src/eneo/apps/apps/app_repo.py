from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Executable
from sqlalchemy.sql.base import ExecutableOption

from eneo.ai_models.completion_models.completion_model import CompletionModelSparse
from eneo.apps.apps.api.app_models import InputField
from eneo.apps.apps.app import App, AppContextValidationInput
from eneo.apps.apps.app_factory import AppFactory
from eneo.database.database import AsyncSession
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.app_table import Apps, AppsFiles, AppsPrompts, InputFields
from eneo.database.tables.prompts_table import Prompts
from eneo.files.file_content_loader import FileAttachmentGroup, FileContentLoader
from eneo.files.file_models import File, FileMetadata, FileType
from eneo.files.file_repo import FileRepository
from eneo.prompts.prompt import Prompt
from eneo.prompts.prompt_repo import PromptRepository
from eneo.transcription_models.domain.transcription_model_repo import (
    TranscriptionModelRepository,
)


class AppRepository:
    def __init__(
        self,
        session: AsyncSession,
        factory: AppFactory,
        file_content_loader: FileContentLoader,
        file_repo: FileRepository,
        prompt_repo: PromptRepository,
        transcription_model_repo: TranscriptionModelRepository,
    ):
        super().__init__()
        self.session = session
        self.factory = factory
        self.file_content_loader = file_content_loader
        self.file_repo = file_repo
        self.prompt_repo = prompt_repo
        self.transcription_model_repo = transcription_model_repo

    async def _load_attachments(
        self,
        records: Sequence[Apps],
    ) -> dict[UUID, list[File]]:
        groups = [
            FileAttachmentGroup(
                owner_kind="app",
                owner_id=record.id,
                tenant_id=record.tenant_id,
                files=tuple(
                    FileMetadata.model_validate(attachment.file)
                    for attachment in record.attachments
                ),
            )
            for record in records
        ]
        loaded = await self.file_content_loader.load_attachment_groups(groups)
        return {record.id: loaded[("app", record.id)] for record in records}

    async def get_by_ids_for_context_validation(
        self,
        *,
        app_ids: Sequence[UUID],
        tenant_id: UUID,
    ) -> dict[UUID, AppContextValidationInput]:
        if not app_ids:
            return {}

        selected_prompt_text = (
            sa.select(Prompts.text)
            .join(AppsPrompts, AppsPrompts.prompt_id == Prompts.id)
            .where(
                AppsPrompts.app_id == Apps.id,
                AppsPrompts.is_selected.is_(True),
            )
            .limit(1)
            .correlate(Apps)
            .scalar_subquery()
        )
        statement = (
            sa.select(Apps, selected_prompt_text.label("prompt_text"))
            .where(
                Apps.id.in_(app_ids),
                Apps.tenant_id == tenant_id,
            )
            .options(
                selectinload(Apps.completion_model).selectinload(
                    CompletionModels.provider
                ),
                selectinload(Apps.attachments).selectinload(AppsFiles.file),
            )
        )
        rows = (await self.session.execute(statement)).all()

        metadata_by_app_id: dict[UUID, list[FileMetadata]] = {}
        app_ids_by_parent_id: defaultdict[UUID, list[UUID]] = defaultdict(list)
        parent_ids: list[UUID] = []
        seen_parent_ids: set[UUID] = set()
        models_by_app_id: dict[UUID, CompletionModelSparse | None] = {}
        prompt_text_by_app_id: dict[UUID, str] = {}
        for record, prompt_text in rows:
            completion_model = (
                self.factory.create_completion_model_sparse(record.completion_model)
                if record.completion_model is not None
                else None
            )
            models_by_app_id[record.id] = completion_model
            prompt_text_by_app_id[record.id] = prompt_text or ""
            metadata = [
                FileMetadata.model_validate(attachment.file)
                for attachment in record.attachments
            ]
            metadata_by_app_id[record.id] = metadata
            if completion_model is None or not completion_model.vision:
                continue
            for file in metadata:
                if file.file_type is not FileType.TEXT:
                    continue
                app_ids_by_parent_id[file.id].append(record.id)
                if file.id not in seen_parent_ids:
                    seen_parent_ids.add(file.id)
                    parent_ids.append(file.id)

        unstable_app_ids: set[UUID] = set()
        if parent_ids:
            projection = await self.file_repo.project_derived_images_for_attached_roots(
                parent_ids=parent_ids,
                tenant_id=tenant_id,
            )
            present_ids_by_app_id = {
                app_id: {metadata.id for metadata in files}
                for app_id, files in metadata_by_app_id.items()
            }
            for metadata in projection.derived_images:
                assert metadata.parent_file_id is not None
                for app_id in app_ids_by_parent_id[metadata.parent_file_id]:
                    if metadata.id in present_ids_by_app_id[app_id]:
                        continue
                    metadata_by_app_id[app_id].append(metadata)
                    present_ids_by_app_id[app_id].add(metadata.id)
            unstable_app_ids = {
                app_id
                for parent_id in projection.unstable_parent_ids
                for app_id in app_ids_by_parent_id[parent_id]
            }

        return {
            app_id: AppContextValidationInput(
                app_id=app_id,
                prompt_text=prompt_text_by_app_id[app_id],
                completion_model=models_by_app_id[app_id],
                completion_file_metadata=tuple(metadata),
                completion_files_stable=app_id not in unstable_app_ids,
            )
            for app_id, metadata in metadata_by_app_id.items()
        }

    async def iter_context_files_for_validation_batches(
        self,
        *,
        validation_inputs: Sequence[AppContextValidationInput],
        tenant_id: UUID,
        max_batch_bytes: int,
    ) -> AsyncIterator[dict[UUID, tuple[File, ...]]]:
        groups = [
            FileAttachmentGroup(
                owner_kind="app",
                owner_id=validation_input.app_id,
                tenant_id=tenant_id,
                files=validation_input.completion_file_metadata,
            )
            for validation_input in validation_inputs
        ]
        async for (
            loaded_groups
        ) in self.file_content_loader.load_attachment_groups_in_payload_batches(
            groups,
            max_batch_bytes=max_batch_bytes,
        ):
            yield {app_id: tuple(files) for (_, app_id), files in loaded_groups.items()}

    def _options(self) -> list[ExecutableOption]:
        return [
            selectinload(Apps.completion_model).selectinload(CompletionModels.provider),
            selectinload(Apps.input_fields),
            selectinload(Apps.attachments).selectinload(AppsFiles.file),
            selectinload(Apps.template),
        ]

    async def _get_record_with_options(self, stmt: Executable) -> Apps | None:
        for option in self._options():
            stmt = stmt.options(option)  # type: ignore[union-attr]  # ORM options on DML stmts

        return await self.session.scalar(stmt)  # type: ignore[arg-type]  # Executable accepted at runtime

    async def _get_selected_prompt(self, app_id: UUID) -> Prompt | None:
        stmt = (
            sa.select(AppsPrompts.prompt_id)
            .where(AppsPrompts.app_id == app_id)
            .where(AppsPrompts.is_selected)
        )

        prompt_id = await self.session.scalar(stmt)

        if prompt_id is None:
            return None

        return await self.prompt_repo.get(prompt_id)

    async def _set_input_fields(
        self, app_in_db: Apps, input_fields: list[InputField]
    ) -> None:
        # Delete all
        stmt = sa.delete(InputFields).where(InputFields.app_id == app_in_db.id)
        await self.session.execute(stmt)

        # Add input_fields
        if input_fields:
            input_fields_dict: list[dict[str, object]] = [
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

    async def _set_prompt(self, app_in_db: Apps, prompt: Prompt) -> None:
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

    async def _set_attachments(self, app_in_db: Apps, attachments: list[File]) -> None:
        # Delete all
        stmt = sa.delete(AppsFiles).where(AppsFiles.app_id == app_in_db.id)
        await self.session.execute(stmt)

        # Add attachments
        if attachments:
            attachments_dicts: list[dict[str, object]] = [
                dict(app_id=app_in_db.id, file_id=file.id) for file in attachments
            ]

            stmt = sa.insert(AppsFiles).values(attachments_dicts)
            await self.session.execute(stmt)

        await self.session.refresh(app_in_db)

    async def add(self, app: App) -> App:
        # Always write the dict — never None — so an INSERT cannot silently
        # re-introduce a NULL kwargs row of the kind we just backfilled away.
        model_kwargs = app.completion_model_kwargs.model_dump()

        transcription_model_id = (
            None if app.transcription_model is None else app.transcription_model.id
        )

        template_id = app.source_template.id if app.source_template else None
        completion_model_id = app.completion_model.id if app.completion_model else None
        stmt = (
            sa.insert(Apps)
            .values(
                name=app.name,
                description=app.description,
                completion_model_kwargs=model_kwargs,
                tenant_id=app.tenant_id,
                user_id=app.user_id,
                space_id=app.space_id,
                completion_model_id=completion_model_id,
                published=app.published,
                template_id=template_id,
                transcription_model_id=transcription_model_id,
            )
            .returning(Apps)
        )

        entry_in_db = await self._get_record_with_options(stmt)
        assert entry_in_db is not None  # INSERT ... RETURNING always returns a row

        if app.prompt is not None:
            await self._set_prompt(entry_in_db, app.prompt)

        await self._set_input_fields(entry_in_db, app.input_fields)
        await self._set_attachments(entry_in_db, app.attachments)

        return self.factory.create_app_from_db(
            entry_in_db,
            attachments=app.attachments,
            prompt=app.prompt,
            transcription_model=app.transcription_model,
        )

    async def get(self, id: UUID) -> App | None:
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

        attachments = await self._load_attachments([entry_in_db])
        return self.factory.create_app_from_db(
            entry_in_db,
            attachments=attachments[entry_in_db.id],
            prompt=prompt,
            transcription_model=transcription_model,
        )

    async def update(self, app: App) -> App:
        # See `add` — same reason: never write NULL back to the column.
        model_kwargs = app.completion_model_kwargs.model_dump()

        transcription_model_id = (
            None if app.transcription_model is None else app.transcription_model.id
        )
        completion_model_id = app.completion_model.id if app.completion_model else None

        stmt = (
            sa.update(Apps)
            .values(
                name=app.name,
                description=app.description,
                completion_model_kwargs=model_kwargs,
                tenant_id=app.tenant_id,
                user_id=app.user_id,
                space_id=app.space_id,
                completion_model_id=completion_model_id,
                transcription_model_id=transcription_model_id,
                published=app.published,
                data_retention_days=app.data_retention_days,
                icon_id=app.icon_id,
            )
            .where(Apps.id == app.id)
            .returning(Apps)
        )

        entry_in_db = await self._get_record_with_options(stmt)
        assert entry_in_db is not None  # UPDATE ... RETURNING always returns a row

        if app.prompt is not None:
            await self._set_prompt(entry_in_db, app.prompt)

        await self._set_input_fields(entry_in_db, app.input_fields)
        await self._set_attachments(entry_in_db, app.attachments)

        return self.factory.create_app_from_db(
            entry_in_db,
            attachments=app.attachments,
            prompt=app.prompt,
            transcription_model=app.transcription_model,
        )

    async def delete(self, id: UUID) -> None:
        stmt = sa.delete(Apps).where(Apps.id == id)
        await self.session.execute(stmt)

    async def get_by_space(self, space_id: UUID) -> list[App]:
        stmt = (
            sa.select(Apps).where(Apps.space_id == space_id).order_by(Apps.created_at)
        )

        for option in self._options():
            stmt = stmt.options(option)

        records = list(await self.session.scalars(stmt))
        attachments = await self._load_attachments(records)

        apps: list[App] = []
        for record in records:
            prompt = await self._get_selected_prompt(record.id)

            # Get transcription model using the repo
            transcription_model = None
            if record.transcription_model_id:
                transcription_model = await self.transcription_model_repo.one(
                    record.transcription_model_id
                )

            app = self.factory.create_app_from_db(
                app_in_db=record,
                attachments=attachments[record.id],
                prompt=prompt,
                transcription_model=transcription_model,
            )
            apps.append(app)

        return apps
