from datetime import datetime
from typing import TYPE_CHECKING, Sequence, cast
from uuid import UUID

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm.base import NO_VALUE
from sqlalchemy.orm.state import InstanceState

from eneo.ai_models.completion_models.completion_model import (
    CompletionModelSparse,
    ModelKwargs,
)
from eneo.apps.apps.api.app_models import InputField, InputFieldType
from eneo.apps.apps.app import App
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.app_table import Apps
from eneo.files.file_models import File
from eneo.prompts.prompt import Prompt
from eneo.prompts.prompt_factory import PromptFactory
from eneo.spaces.space import Space
from eneo.transcription_models.domain.transcription_model import TranscriptionModel
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.templates.app_template.app_template import AppTemplate
    from eneo.templates.app_template.app_template_factory import AppTemplateFactory


class AppFactory:
    def __init__(
        self,
        app_template_factory: "AppTemplateFactory",
    ):
        super().__init__()
        self.app_template_factory = app_template_factory

    @staticmethod
    def _create_model_kwargs(
        completion_model_kwargs: object | None,
    ) -> ModelKwargs:
        # Delegating to model_validate (instead of a manual `.get(...)` walk)
        # is deliberate: a corrupt non-dict JSONB value raises ValidationError,
        # which `_build_or_skip` in space_factory can catch and isolate per-row.
        # A `.get` walk would raise AttributeError, bypass that belt and crash
        # the whole space load.
        if completion_model_kwargs is None:
            return ModelKwargs()
        return ModelKwargs.model_validate(completion_model_kwargs)

    @staticmethod
    def _create_completion_model_sparse(
        completion_model: CompletionModels,
    ) -> CompletionModelSparse:
        sparse_model = CompletionModelSparse.model_validate(completion_model)
        model_state = cast(
            InstanceState[CompletionModels], sa_inspect(completion_model)
        )
        provider_state = model_state.attrs.provider
        if provider_state.loaded_value is NO_VALUE:
            return sparse_model

        provider = provider_state.value
        if provider is None:
            return sparse_model

        return sparse_model.model_copy(update={"provider_type": provider.provider_type})

    def create_app(
        self,
        user: UserInDB,
        space: Space,
        name: str,
        completion_model: "CompletionModel",
        transcription_model: TranscriptionModel,
        input_fields: list[InputField] | None = None,
    ) -> App:
        if input_fields is None:
            input_fields = [InputField(type=InputFieldType.TEXT_FIELD)]

        space_id = space.id
        if space_id is None:
            raise ValueError("Space must have an id before creating an app")

        return App(
            created_at=None,
            updated_at=None,
            id=None,
            user_id=user.id,
            tenant_id=user.tenant_id,
            space_id=space_id,
            name=name,
            description=None,
            prompt=None,
            completion_model=completion_model,
            # ModelKwargs is required on the domain object; reads, .model_dump
            # writes and the AppPublic response all rely on it being present.
            completion_model_kwargs=ModelKwargs(),
            input_fields=input_fields,
            attachments=[],
            published=False,
            transcription_model=transcription_model,
        )

    def create_app_from_template(
        self,
        user: "UserInDB",
        template: "AppTemplate",
        space: Space,
        completion_model: "CompletionModel",
        input_fields: list[InputField],
        name: str | None = None,
        prompt: Prompt | None = None,
        attachments: Sequence["File"] | None = None,
        transcription_model: TranscriptionModel | None = None,
    ) -> App:
        space_id = space.id
        if space_id is None:
            raise ValueError("Space must have an id before creating an app")

        attachment_list = list(attachments) if attachments is not None else []

        app = App(
            user_id=user.id,
            tenant_id=user.tenant_id,
            space_id=space_id,
            name=name or template.name,
            description=template.description,
            prompt=prompt,
            attachments=attachment_list,
            completion_model_kwargs=self._create_model_kwargs(
                template.completion_model_kwargs
            ),
            input_fields=input_fields,
            created_at=None,
            updated_at=None,
            id=None,
            completion_model=completion_model,
            published=False,
            source_template=template,
            transcription_model=transcription_model,
        )

        return app

    def create_app_from_db(
        self,
        app_in_db: Apps,
        prompt: Prompt | None = None,
        transcription_model: TranscriptionModel | None = None,
    ) -> App:
        completion_model = (
            self._create_completion_model_sparse(app_in_db.completion_model)
            if app_in_db.completion_model is not None
            else None
        )
        model_kwargs = self._create_model_kwargs(app_in_db.completion_model_kwargs)
        input_fields = [
            InputField.model_validate(input_field)
            for input_field in app_in_db.input_fields
        ]
        attachments = [
            File.model_validate(attachment.file) for attachment in app_in_db.attachments
        ]
        if completion_model is not None:
            model_kwargs = model_kwargs.filter_unsupported(
                completion_model.supported_model_kwargs
            )

        source_template = (
            self.app_template_factory.create_app_template(app_in_db.template)
            if app_in_db.template
            else None
        )

        return App(
            created_at=cast(datetime | None, app_in_db.created_at),
            updated_at=cast(datetime | None, app_in_db.updated_at),
            id=cast(UUID | None, app_in_db.id),
            space_id=app_in_db.space_id,
            user_id=app_in_db.user_id,
            tenant_id=app_in_db.tenant_id,
            name=app_in_db.name,
            description=app_in_db.description,
            prompt=prompt,
            completion_model=completion_model,
            completion_model_kwargs=model_kwargs,
            input_fields=input_fields,
            attachments=attachments,
            published=app_in_db.published,
            source_template=source_template,
            transcription_model=transcription_model,
            data_retention_days=app_in_db.data_retention_days,
            icon_id=app_in_db.icon_id,
        )

    def create_space_app_from_db(
        self,
        app_in_db: Apps,
        completion_models: Sequence["CompletionModel"] | None = None,
        transcription_models: Sequence[TranscriptionModel] | None = None,
    ) -> App:
        completion_models = completion_models or []
        transcription_models = transcription_models or []

        prompt_in_db = getattr(app_in_db, "prompt", None)
        if prompt_in_db is not None:
            prompt = PromptFactory.create_prompt_from_db(
                prompt_in_db=prompt_in_db,
                is_selected=True,
            )
        else:
            prompt = None

        input_fields = [
            InputField.model_validate(input_field)
            for input_field in app_in_db.input_fields
        ]
        model_kwargs = self._create_model_kwargs(app_in_db.completion_model_kwargs)
        attachments = [
            File.model_validate(attachment.file) for attachment in app_in_db.attachments
        ]

        source_template = (
            self.app_template_factory.create_app_template(app_in_db.template)
            if app_in_db.template
            else None
        )

        completion_model = next(
            (
                model
                for model in completion_models
                if model.id == app_in_db.completion_model_id
            ),
            None,
        )
        if completion_model is not None:
            model_kwargs = model_kwargs.filter_unsupported(
                completion_model.get_supported_model_kwargs()
            )

        transcription_model = next(
            (
                model
                for model in transcription_models
                if model.id == app_in_db.transcription_model_id
            ),
            None,
        )

        return App(
            created_at=cast(datetime | None, app_in_db.created_at),
            updated_at=cast(datetime | None, app_in_db.updated_at),
            id=cast(UUID | None, app_in_db.id),
            space_id=app_in_db.space_id,
            user_id=app_in_db.user_id,
            tenant_id=app_in_db.tenant_id,
            name=app_in_db.name,
            description=app_in_db.description,
            prompt=prompt,
            completion_model=completion_model,
            completion_model_kwargs=model_kwargs,
            input_fields=input_fields,
            attachments=attachments,
            published=app_in_db.published,
            source_template=source_template,
            transcription_model=transcription_model,
            data_retention_days=app_in_db.data_retention_days,
            icon_id=app_in_db.icon_id,
        )
