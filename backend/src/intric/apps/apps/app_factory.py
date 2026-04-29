from datetime import datetime
from typing import TYPE_CHECKING, Sequence, cast
from uuid import UUID

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm.base import NO_VALUE
from sqlalchemy.orm.state import InstanceState

from intric.ai_models.completion_models.completion_model import (
    CompletionModelSparse,
    ModelKwargs,
)
from intric.apps.apps.api.app_models import InputField, InputFieldType
from intric.apps.apps.app import App
from intric.database.tables.ai_models_table import CompletionModels
from intric.database.tables.app_table import Apps
from intric.files.file_models import File
from intric.prompts.prompt import Prompt
from intric.prompts.prompt_factory import PromptFactory
from intric.spaces.space import Space
from intric.transcription_models.domain.transcription_model import TranscriptionModel
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.completion_models.domain.completion_model import CompletionModel
    from intric.templates.app_template.app_template import AppTemplate
    from intric.templates.app_template.app_template_factory import AppTemplateFactory


class AppFactory:
    def __init__(
        self,
        app_template_factory: "AppTemplateFactory",
    ):
        super().__init__()
        self.app_template_factory = app_template_factory

    @staticmethod
    def _create_model_kwargs(
        completion_model_kwargs: dict[str, object] | None,
    ) -> ModelKwargs | None:
        if completion_model_kwargs is None:
            return None

        return ModelKwargs(
            temperature=cast(float | None, completion_model_kwargs.get("temperature")),
            top_p=cast(float | None, completion_model_kwargs.get("top_p")),
            reasoning_effort=cast(
                str | None, completion_model_kwargs.get("reasoning_effort")
            ),
            verbosity=cast(str | None, completion_model_kwargs.get("verbosity")),
            response_format=cast(
                dict[str, object] | None, completion_model_kwargs.get("response_format")
            ),
            presence_penalty=cast(
                float | None, completion_model_kwargs.get("presence_penalty")
            ),
            frequency_penalty=cast(
                float | None, completion_model_kwargs.get("frequency_penalty")
            ),
            top_k=cast(int | None, completion_model_kwargs.get("top_k")),
        )

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
            completion_model_kwargs=None,
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
        raw_completion_model_kwargs = cast(
            dict[object, object] | None, app_in_db.completion_model_kwargs
        )
        completion_model_kwargs = (
            {str(key): value for key, value in raw_completion_model_kwargs.items()}
            if raw_completion_model_kwargs is not None
            else None
        )
        input_fields = [
            InputField.model_validate(input_field)
            for input_field in app_in_db.input_fields
        ]
        attachments = [
            File.model_validate(attachment.file) for attachment in app_in_db.attachments
        ]
        model_kwargs = self._create_model_kwargs(completion_model_kwargs)

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
        raw_completion_model_kwargs = cast(
            dict[object, object] | None, app_in_db.completion_model_kwargs
        )
        completion_model_kwargs = (
            {str(key): value for key, value in raw_completion_model_kwargs.items()}
            if raw_completion_model_kwargs is not None
            else None
        )
        attachments = [
            File.model_validate(attachment.file) for attachment in app_in_db.attachments
        ]
        model_kwargs = self._create_model_kwargs(completion_model_kwargs)

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
