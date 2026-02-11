from typing import TYPE_CHECKING, Optional, Union
from uuid import UUID

from intric.ai_models.completion_models.completion_model import ModelKwargs
from intric.apps.apps.api.app_models import InputField, InputFieldType
from intric.apps.apps.app import App
from intric.apps.apps.app_factory import AppFactory
from intric.apps.apps.app_repo import AppRepository
from intric.files.file_service import FileService
from intric.files.transcriber import Transcriber
from intric.icons.icon_repo import IconRepository
from intric.main.logging import get_logger
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.main.models import NOT_PROVIDED, ModelId, NotProvided, ResourcePermission
from intric.prompts.prompt_service import PromptService
from intric.spaces.api.space_models import WizardType
from intric.spaces.space import Space
from intric.users.user import UserInDB
from intric.authentication.api_key_scope_revoker import ApiKeyScopeRevoker
from intric.authentication.auth_models import ApiKeyScopeType, ApiKeyStateReasonCode

if TYPE_CHECKING:
    from intric.actors import ActorManager
    from intric.completion_models.application import CompletionModelCRUDService
    from intric.completion_models.domain.completion_model import CompletionModel
    from intric.completion_models.infrastructure.completion_service import (
        CompletionService,
    )
    from intric.prompts.prompt import Prompt
    from intric.spaces.api.space_models import TemplateCreate
    from intric.spaces.space_repo import SpaceRepository
    from intric.templates.app_template.app_template_service import AppTemplateService
    from intric.transcription_models.application.transcription_model_crud_service import (
        TranscriptionModelCRUDService,
    )
    from intric.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )


class AppService:
    def __init__(
        self,
        user: UserInDB,
        repo: AppRepository,
        space_repo: "SpaceRepository",
        factory: AppFactory,
        completion_model_crud_service: "CompletionModelCRUDService",
        file_service: FileService,
        prompt_service: PromptService,
        transcriber: Transcriber,
        app_template_service: "AppTemplateService",
        actor_manager: "ActorManager",
        transcription_model_crud_service: "TranscriptionModelCRUDService",
        completion_service: "CompletionService",
        icon_repo: IconRepository,
        api_key_scope_revoker: ApiKeyScopeRevoker | None = None,
    ):
        self.user = user
        self.repo = repo
        self.space_repo = space_repo
        self.factory = factory
        self.completion_model_crud_service = completion_model_crud_service
        self.file_service = file_service
        self.prompt_service = prompt_service
        self.transcriber = transcriber
        self.app_template_service = app_template_service
        self.actor_manager = actor_manager
        self.transcription_model_crud_service = transcription_model_crud_service
        self.completion_service = completion_service
        self.icon_repo = icon_repo
        self.api_key_scope_revoker = api_key_scope_revoker
        self._logger = get_logger(__name__)

    async def create_app(
        self, name: str, space: Space, template_data: Optional["TemplateCreate"] = None
    ) -> tuple[App, list[ResourcePermission]]:
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_create_apps():
            raise UnauthorizedException()

        completion_model = await self.get_completion_model(space=space)
        transcription_model = await self.get_transcription_model(space=space)

        if not template_data:
            app = self.factory.create_app(
                user=self.user,
                space=space,
                name=name,
                completion_model=completion_model,
                transcription_model=transcription_model,
            )
            app_in_db = await self.repo.add(app)
        else:
            app_in_db = await self._create_from_template(
                space=space,
                template_data=template_data,
                name=name,
                completion_model=completion_model,
                transcription_model=transcription_model,
            )

        # TODO: Review how we get the permissions to the presentation layer
        permissions = actor.get_app_permissions()

        return app_in_db, permissions

    async def _create_from_template(
        self,
        space: "Space",
        template_data: "TemplateCreate",
        completion_model: Optional["CompletionModel"],
        name: str | None = None,
        transcription_model: Optional["TranscriptionModel"] = None,
    ):
        template = await self.app_template_service.get_app_template(
            app_template_id=template_data.id
        )

        # Validate incoming data
        template.validate_wizard_data(template_data=template_data)

        attachments = await self.file_service.get_file_infos(
            file_ids=template_data.get_ids_by_type(wizard_type=WizardType.attachments)
        )

        prompt = None
        if template.prompt_text:
            prompt = await self.prompt_service.create_prompt(text=template.prompt_text)

        input_fields = [
            InputField(
                type=InputFieldType(template.input_type),
                description=template.input_description,
            )
        ]

        app = self.factory.create_app_from_template(
            user=self.user,
            template=template,
            name=name or template.name,
            prompt=prompt,
            attachments=attachments,
            completion_model=completion_model,
            input_fields=input_fields,
            space=space,
            transcription_model=transcription_model,
        )

        return await self.repo.add(app)

    async def get_completion_model(self, space: Space) -> Optional["CompletionModel"]:
        """Get a completion model for the space. Returns None if no model is available."""
        completion_model = space.get_default_completion_model() or (
            space.get_latest_completion_model()
            if not space.is_personal()
            else await self.completion_model_crud_service.get_default_completion_model()
        )

        return completion_model

    async def get_transcription_model(
        self, space: Space
    ) -> Optional["TranscriptionModel"]:
        """Get a transcription model for the space. Returns None if no model is available."""
        transcription_model = space.get_latest_transcription_model()
        if not transcription_model:
            # Get default from tenant (for both personal and non-personal spaces)
            transcription_model = await self.transcription_model_crud_service.get_default_transcription_model()

        if transcription_model is None:
            raise BadRequestException(
                "No transcription model available. Please enable a transcription model in the space before creating an app."
            )

        return transcription_model

    async def get_app(self, app_id: UUID) -> tuple[App, list[ResourcePermission]]:
        space = await self.space_repo.get_space_by_app(app_id=app_id)
        app = space.get_app(app_id=app_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_read_apps():
            raise UnauthorizedException()

        # TODO: Review how we get the permissions to the presentation layer
        permissions = actor.get_app_permissions()

        return app, permissions

    async def update_app(
        self,
        app_id: UUID,
        name: str | None = None,
        description: str | None = None,
        completion_model_id: UUID | None = None,
        completion_model_kwargs: ModelKwargs | None = None,
        input_fields: list[InputField] | None = None,
        attachment_ids: list[ModelId] | None = None,
        prompt_text: str | None = None,
        prompt_description: str | None = None,
        transcription_model_id: UUID | None = None,
        data_retention_days: Union[int, None, NotProvided] = NOT_PROVIDED,
        icon_id: Union[UUID, None, NotProvided] = NOT_PROVIDED,
    ) -> tuple[App, list[ResourcePermission]]:
        space = await self.space_repo.get_space_by_app(app_id=app_id)
        app = space.get_app(app_id=app_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_edit_apps():
            raise UnauthorizedException()

        completion_model = None
        if completion_model_id is not None:
            if not space.is_completion_model_in_space(
                completion_model_id=completion_model_id
            ):
                raise BadRequestException(
                    "The completion model is not enabled in the space."
                )

            else:
                completion_model = (
                    await self.completion_model_crud_service.get_completion_model(
                        completion_model_id
                    )
                )

        transcription_model = None
        if transcription_model_id is not None:
            if not space.is_transcription_model_in_space(
                transcription_model_id=transcription_model_id
            ):
                raise BadRequestException(
                    "The transcription model is not enabled in the space."
                )
            else:
                transcription_model = (
                    await self.transcription_model_crud_service.get_transcription_model(
                        model_id=transcription_model_id
                    )
                )

        attachments = None
        if attachment_ids is not None:
            attachments = await self.file_service.get_file_infos(
                [attachment.id for attachment in attachment_ids]
            )

        prompt = None
        if prompt_text is not None:
            prompt = await self.prompt_service.create_prompt(
                text=prompt_text, description=prompt_description
            )

        app.update(
            name=name,
            description=description,
            completion_model=completion_model,
            completion_model_kwargs=completion_model_kwargs,
            input_fields=input_fields,
            attachments=attachments,
            prompt=prompt,
            transcription_model=transcription_model,
            data_retention_days=data_retention_days,
            icon_id=icon_id,
        )

        app_in_db = await self.repo.update(app)

        # TODO: Review how we get the permissions to the presentation layer
        permissions = actor.get_app_permissions()

        return app_in_db, permissions

    async def delete_app(self, app_id: UUID):
        space = await self.space_repo.get_space_by_app(app_id=app_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_delete_apps():
            raise UnauthorizedException()

        app = space.get_app(app_id=app_id)
        icon_id = app.icon_id

        if self.api_key_scope_revoker is not None:
            try:
                await self.api_key_scope_revoker.revoke_scope(
                    scope_type=ApiKeyScopeType.APP,
                    scope_id=app_id,
                    reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
                    reason_text="App deleted",
                )
            except Exception:
                self._logger.exception(
                    "Failed to revoke API keys for deleted app",
                    extra={"app_id": str(app_id)},
                )

        await self.repo.delete(app_id)

        if icon_id:
            await self.icon_repo.delete(icon_id)

    async def run_app(self, app_id: UUID, file_ids: list[UUID], text: str | None):
        space = await self.space_repo.get_space_by_app(app_id=app_id)
        app = space.get_app(app_id=app_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_read_app(app=app):
            raise UnauthorizedException()

        if not space.can_run_app(app=app):
            raise UnauthorizedException()

        files = await self.file_service.get_files_by_ids(
            file_ids=file_ids, include_transcription=True
        )

        return await app.run(
            files=files,
            text=text,
            completion_service=self.completion_service,
            transcriber=self.transcriber,
        )

    async def get_prompts_by_app(self, app_id: UUID) -> list["Prompt"]:
        space = await self.space_repo.get_space_by_app(app_id=app_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_read_prompts_of_apps():
            raise UnauthorizedException()

        return await self.prompt_service.get_prompts_by_app(app_id=app_id)

    async def publish_app(self, app_id: "UUID", publish: bool):
        space = await self.space_repo.get_space_by_app(app_id=app_id)
        app = space.get_app(app_id=app_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_publish_apps():
            raise UnauthorizedException()

        app.update(published=publish)

        app_in_db = await self.repo.update(app)

        # TODO: Review how we get the permissions to the presentation layer
        permissions = actor.get_app_permissions()

        return app_in_db, permissions
