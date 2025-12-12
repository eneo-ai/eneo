from dataclasses import dataclass
from typing import TYPE_CHECKING, Union
from uuid import UUID

from intric.completion_models.application.completion_model_crud_service import (
    CompletionModelCRUDService,
)
from intric.completion_models.domain.completion_model_service import (
    CompletionModelService,
)
from intric.embedding_models.application.embedding_model_crud_service import (
    EmbeddingModelCRUDService,
)
from intric.icons.icon_repo import IconRepository
from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from sqlalchemy.exc import IntegrityError
from intric.main.exceptions import UniqueException
from intric.main.models import NOT_PROVIDED, ModelId, NotProvided
from intric.spaces.api.space_models import SpaceMember, SpaceRoleValue
from intric.spaces.space import Space
from intric.spaces.space_factory import SpaceFactory
from intric.spaces.space_repo import SpaceRepository
from intric.transcription_models.application.transcription_model_crud_service import (
    TranscriptionModelCRUDService,
)
from intric.transcription_models.domain.transcription_model_service import (
    TranscriptionModelService,
)
from intric.users.user import UserInDB
from intric.users.user_repo import UsersRepository

if TYPE_CHECKING:
    from intric.actors import ActorManager
    from intric.completion_models.domain import CompletionModel
    from intric.embedding_models.domain import EmbeddingModel
    from intric.security_classifications.application.security_classification_service import (
        SecurityClassificationService,
    )
    from intric.transcription_models.domain import TranscriptionModel


@dataclass
class SpaceSecurityClassificationImpactAnalysis:
    space: Space
    affected_completion_models: list["CompletionModel"]
    affected_embedding_models: list["EmbeddingModel"]
    affected_transcription_models: list["TranscriptionModel"]

TENANT_SPACE_NAME = "Organization space" 

class SpaceService:
    def __init__(
        self,
        user: UserInDB,
        factory: SpaceFactory,
        repo: SpaceRepository,
        user_repo: UsersRepository,
        embedding_model_crud_service: EmbeddingModelCRUDService,
        completion_model_crud_service: CompletionModelCRUDService,
        completion_model_service: CompletionModelService,
        transcription_model_crud_service: TranscriptionModelCRUDService,
        transcription_model_service: TranscriptionModelService,
        actor_manager: "ActorManager",
        security_classification_service: "SecurityClassificationService",
        icon_repo: IconRepository,
    ):
        self.user = user
        self.factory = factory
        self.repo = repo
        self.user_repo = user_repo
        self.embedding_model_crud_service = embedding_model_crud_service
        self.completion_model_crud_service = completion_model_crud_service
        self.completion_model_service = completion_model_service
        self.transcription_model_crud_service = transcription_model_crud_service
        self.transcription_model_service = transcription_model_service
        self.actor_manager = actor_manager
        self.security_classification_service = security_classification_service
        self.icon_repo = icon_repo

    @staticmethod
    def is_org_space(space: Space) -> bool:
        return space.user_id is None and space.tenant_space_id is None

    def _get_actor(self, space: Space):
        return self.actor_manager.get_space_actor_from_space(space)

    async def create_space(self, name: str):
        hub = await self.get_or_create_tenant_space()
        space = self.factory.create_space(
            name=name, 
            tenant_id=self.user.tenant_id, 
            tenant_space_id=getattr(hub, "id", None)
        )

        def _get_latest_model(models):
            for model in sorted(models, key=lambda model: model.created_at, reverse=True):
                if model.can_access:
                    return model

        # Set embedding models as only the latest one
        embedding_models = await self.embedding_model_crud_service.get_embedding_models()
        latest_embedding_model = _get_latest_model(embedding_models)
        space.embedding_models = [latest_embedding_model] if latest_embedding_model else []

        # Set completion models
        completion_models = await self.completion_model_service.get_available_completion_models()
        space.completion_models = completion_models

        # Set transcription models as only the default one
        transcription_model = await self.transcription_model_service.get_default_model()

        if transcription_model is None:
            transcription_models = []
        else:
            transcription_models = [transcription_model]

        space.transcription_models = transcription_models

        # Set admin
        admin = SpaceMember(
            id=self.user.id,
            username=self.user.username,
            email=self.user.email,
            role=SpaceRoleValue.ADMIN,
        )
        space.add_member(admin)

        return await self.repo.add(space)

    async def get_space(self, id: UUID) -> Space:
        space = await self.repo.one(id)

        actor = self._get_actor(space)
        if not actor.can_read_space():
            raise UnauthorizedException()

        return space

    async def update_space(
        self,
        id: UUID,
        name: str = None,
        description: str = None,
        embedding_model_ids: list[UUID] = None,
        completion_model_ids: list[UUID] = None,
        transcription_model_ids: list[UUID] = None,
        security_classification: Union[ModelId, NotProvided, None] = NOT_PROVIDED,
        icon_id: Union[UUID, None, NotProvided] = NOT_PROVIDED,
    ) -> Space:
        space = await self.get_space(id)
        actor = self._get_actor(space)

        if not actor.can_edit_space():
            raise UnauthorizedException("User does not have permission to edit space")

        space_security_classification = None
        if security_classification is not NOT_PROVIDED:
            if not self.user.tenant.security_enabled:
                raise BadRequestException("Security is not enabled for this tenant")
            if security_classification is not None:
                space_security_classification = (
                    await self.security_classification_service.get_security_classification(  # noqa: E501
                        security_classification.id
                    )
                )
                if space_security_classification is None:
                    raise BadRequestException("Security classification not found")

        completion_models = None
        if completion_model_ids is not None:
            completion_models = [
                await self.completion_model_crud_service.get_completion_model(model_id=model_id)
                for model_id in completion_model_ids
            ]

        embedding_models = None
        if embedding_model_ids is not None:
            embedding_models = []
            for model_id in embedding_model_ids:
                model = await self.embedding_model_crud_service.get_embedding_model(model_id)
                if model:
                    embedding_models.append(model)

        transcription_models = None
        if transcription_model_ids is not None:
            transcription_models = [
                await self.transcription_model_crud_service.get_transcription_model(
                    model_id=model_id
                )
                for model_id in transcription_model_ids
            ]

        space.update(
            name=name,
            description=description,
            completion_models=completion_models,
            embedding_models=embedding_models,
            transcription_models=transcription_models,
            security_classification=(
                space_security_classification
                if security_classification is not NOT_PROVIDED
                else NOT_PROVIDED
            ),
            icon_id=icon_id,
        )

        return await self.repo.update(space)

    async def security_classification_impact_analysis(
        self, id: UUID, security_classification_id: UUID
    ) -> SpaceSecurityClassificationImpactAnalysis:
        space = await self.get_space(id)
        actor = self._get_actor(space)

        if not actor.can_edit_space():
            raise UnauthorizedException("User does not have permission to edit space")

        security_classification = (
            await self.security_classification_service.get_security_classification(  # noqa: E501
                security_classification_id
            )
        )
        if security_classification is None:
            raise BadRequestException("Security classification not found")

        current_completion_models = space.completion_models
        current_embedding_models = space.embedding_models
        current_transcription_models = space.transcription_models

        space.update(
            security_classification=security_classification,
        )

        remaining_completion_model_ids = [cm.id for cm in space.completion_models]
        remaining_embedding_model_ids = [em.id for em in space.embedding_models]
        remaining_transcription_model_ids = [tm.id for tm in space.transcription_models]

        affected_completion_models = [
            cm for cm in current_completion_models if cm.id not in remaining_completion_model_ids
        ]
        affected_embedding_models = [
            em for em in current_embedding_models if em.id not in remaining_embedding_model_ids
        ]
        affected_transcription_models = [
            tm
            for tm in current_transcription_models
            if tm.id not in remaining_transcription_model_ids
        ]

        affected_assistants = []
        for assistant in space.assistants:
            if assistant.completion_model.id not in remaining_completion_model_ids:
                affected_assistants.append(assistant)
            if (
                assistant.embedding_model_id is not None
                and assistant.embedding_model_id not in remaining_embedding_model_ids
            ):
                if assistant not in affected_assistants:
                    affected_assistants.append(assistant)

        affected_group_chats = []
        for group_chat in space.group_chats:
            for assistant in group_chat.get_assistants():
                if assistant.id in [a.id for a in affected_assistants]:
                    if group_chat not in affected_group_chats:
                        affected_group_chats.append(group_chat)

        affected_apps = []
        for app in space.apps:
            if app.completion_model.id not in remaining_completion_model_ids:
                affected_apps.append(app)
            if app.transcription_model.id not in remaining_transcription_model_ids:
                if app not in affected_apps:
                    affected_apps.append(app)

        affected_services = []
        for service in space.services:
            if service.completion_model.id not in remaining_completion_model_ids:
                affected_services.append(service)
            for group in service.groups:
                if group.embedding_model.id not in remaining_embedding_model_ids:
                    if service not in affected_services:
                        affected_services.append(service)

        space.assistants = affected_assistants
        space.group_chats = affected_group_chats
        space.apps = affected_apps
        space.services = affected_services

        return SpaceSecurityClassificationImpactAnalysis(
            space=space,
            affected_completion_models=affected_completion_models,
            affected_embedding_models=affected_embedding_models,
            affected_transcription_models=affected_transcription_models,
        )

    async def delete_personal_space(self, user: UserInDB):
        space = await self.repo.get_personal_space(user.id)

        if space is not None:
            await self.repo.delete(space.id)

    async def delete_space(self, id: UUID):
        space = await self.get_space(id)
        actor = self._get_actor(space)

        if not actor.can_delete_space():
            raise UnauthorizedException("User does not have permission to delete space")

        icon_id = space.icon_id

        await self.repo.delete(space.id)

        if icon_id:
            await self.icon_repo.delete(icon_id)

    async def get_spaces(
        self, *, include_personal: bool = False, include_applications: bool = False
    ) -> list[Space]:
        spaces = await self.repo.get_spaces_for_member(
            self.user.id, include_applications=include_applications
        )

        if include_personal:
            personal_space = await self.get_personal_space()
            return [personal_space] + spaces

        return spaces

    async def add_member(self, id: UUID, member_id: UUID, role: SpaceRoleValue):
        space = await self.get_space(id)
        actor = self._get_actor(space)

        if not actor.can_edit_space():
            raise UnauthorizedException("Only Admins of the space can add members")

        user = await self.user_repo.get_user_by_id_and_tenant_id(
            id=member_id, tenant_id=self.user.tenant_id
        )

        if user is None:
            raise NotFoundException("User not found")

        member = SpaceMember(
            id=member_id,
            username=user.username,
            email=user.email,
            role=role,
        )

        space.add_member(member)
        space = await self.repo.update(space)

        return space.get_member(member.id)

    async def remove_member(self, id: UUID, user_id: UUID):
        if user_id == self.user.id:
            raise BadRequestException("Can not remove yourself")

        space = await self.get_space(id)
        actor = self._get_actor(space)

        if not actor.can_edit_space():
            raise UnauthorizedException("Only Admins of the space can remove members")

        space.remove_member(user_id)

        await self.repo.update(space)

    async def change_role_of_member(self, id: UUID, user_id: UUID, new_role: SpaceRoleValue):
        if user_id == self.user.id:
            raise BadRequestException("Can not change role of yourself")

        space = await self.get_space(id)
        actor = self._get_actor(space)

        if not actor.can_edit_space():
            raise UnauthorizedException("Only Admins of the space can change the roles of members")

        space.change_member_role(user_id, new_role)
        space = await self.repo.update(space)

        return space.get_member(user_id)

    async def create_personal_space(self):
        hub = await self.get_or_create_tenant_space()
        space_name = f"{self.user.username}'s personal space"
        space = self.factory.create_space(
            name=space_name, 
            user_id=self.user.id, 
            tenant_id=self.user.tenant_id,
            tenant_space_id=getattr(hub, "id", None),
        )

        # Set tenant
        space.tenant_id = self.user.tenant_id

        space_in_db = await self.repo.add(space)

        return space_in_db

    async def get_personal_space(self): 
        return await self.repo.get_personal_space(self.user.id)

    async def _get_space_by_resource(self, space: Space) -> Space:
        actor = self._get_actor(space)

        if not actor.can_read_space():
            raise UnauthorizedException()

        return space

    async def get_space_by_group_chat(self, group_chat_id: UUID) -> Space:
        space = await self.repo.get_space_by_group_chat(group_chat_id=group_chat_id)
        return await self._get_space_by_resource(space)

    async def get_space_by_assistant(self, assistant_id: UUID) -> Space:
        space = await self.repo.get_space_by_assistant(assistant_id=assistant_id)
        return await self._get_space_by_resource(space)

    async def get_space_by_session(self, session_id: UUID) -> Space:
        space = await self.repo.get_space_by_session(session_id=session_id)
        return await self._get_space_by_resource(space)

    async def get_space_by_website(self, website_id: UUID) -> Space:
        space = await self.repo.get_space_by_website(website_id=website_id)
        return await self._get_space_by_resource(space)

    async def get_space_by_collection(self, group_id: UUID) -> Space:
        space = await self.repo.get_space_by_collection(collection_id=group_id)
        return await self._get_space_by_resource(space)

    async def get_space_by_service(self, service_id: UUID) -> Space:
        space = await self.repo.get_space_by_service(service_id=service_id)
        return await self._get_space_by_resource(space)



    async def get_knowledge_for_space(self, space_id: UUID):
        space = await self.get_space(space_id)
        return (
            space.collections,
            space.websites,
            space.integration_knowledge_list,
        )
    
    async def ensure_org_admin_members(self, hub: "Space") -> "Space":
        admins = await self.user_repo.list_tenant_admins(self.user.tenant_id)
        added = False
        for u in admins:
            if u.id not in hub.members:
                hub.members[u.id] = SpaceMember(
                    id=u.id,
                    username=u.username,
                    email=u.email,
                    role=SpaceRoleValue.ADMIN,
                )
                added = True
        if added:
            hub = await self.repo.update(hub)
        return hub

    async def get_or_create_tenant_space(self) -> "Space":
        hub = await self.repo.get_space_by_name_and_tenant(
            name=TENANT_SPACE_NAME, tenant_id=self.user.tenant_id
        )
        if hub is not None:
            hub = await self.ensure_org_admin_members(hub)
            return hub

        try:
            async with self.repo.session.begin_nested():
                hub = self.factory.create_space(
                    name=TENANT_SPACE_NAME,
                    tenant_id=self.user.tenant_id,
                    user_id=None,
                    description="Delad knowledge för hela tenant",
                )
                hub = await self.repo.add(hub)
        except (IntegrityError, UniqueException):
            hub = await self.repo.get_space_by_name_and_tenant(
                name=TENANT_SPACE_NAME, tenant_id=self.user.tenant_id
            )
            if hub is None:
                raise

        hub = await self.ensure_org_admin_members(hub)
        return hub