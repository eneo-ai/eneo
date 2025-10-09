from typing import TYPE_CHECKING

from intric.assistants.api.assistant_models import AssistantSparse
from intric.collections.presentation.collection_models import CollectionPublic
from intric.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelPublic,
)
from intric.group_chat.presentation.models import GroupChatSparse
from intric.integration.presentation.assemblers.integration_knowledge_assembler import (
    IntegrationKnowledgeAssembler,
)
from intric.integration.presentation.models import IntegrationKnowledgePublic
from intric.main.models import PaginatedPermissions, ResourcePermission
from intric.security_classifications.presentation.security_classification_models import (
    SecurityClassificationPublic,
)
from intric.services.service import Service, ServiceSparse
from intric.spaces.api.space_models import (
    Applications,
    AppSparse,
    CreateSpaceServiceResponse,
    Knowledge,
    SpaceDashboard,
    SpaceMember,
    SpacePublic,
    SpaceRole,
    SpaceSparse,
    UpdateSpaceDryRunResponse,
)
from intric.spaces.space import Space
from intric.spaces.space_service import SpaceSecurityClassificationImpactAnalysis
from intric.transcription_models.presentation import TranscriptionModelPublic
from intric.users.user import UserInDB
from intric.websites.presentation.website_models import WebsitePublic

if TYPE_CHECKING:
    from intric.actors import ActorManager
    from intric.assistants.api.assistant_assembler import AssistantAssembler
    from intric.assistants.assistant import Assistant
    from intric.completion_models.presentation import CompletionModelAssembler
    from intric.group_chat.domain.entities.group_chat import GroupChat


class SpaceAssembler:
    def __init__(
        self,
        user: UserInDB,
        assistant_assembler: "AssistantAssembler",
        completion_model_assembler: "CompletionModelAssembler",
        actor_manager: "ActorManager",
    ):
        self.user = user
        self.assistant_assembler = assistant_assembler
        self.completion_model_assembler = completion_model_assembler
        self.actor_manager = actor_manager

    def _set_permissions_on_resources(self, space: Space):
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        for assistant in space.assistants:
            assistant.permissions = actor.get_assistant_permissions(assistant=assistant)

        for group_chat in space.group_chats:
            group_chat.permissions = actor.get_group_chat_permissions(group_chat=group_chat)

        for app in space.apps:
            app.permissions = actor.get_app_permissions()

        for service in space.services:
            service.permissions = actor.get_service_permissions()

        for collection in space.collections:
            collection.permissions = actor.get_collection_permissions()

        for website in space.websites:
            website.permissions = actor.get_website_permissions()

        for knowledge in space.integration_knowledge_list:
            knowledge.permissions = actor.get_integration_knowledge_list_permissions()

    def _get_assistant_permissions(self, space: Space):
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions = []

        if actor.can_read_assistants():
            permissions.append(ResourcePermission.READ)
        if actor.can_create_assistants():
            permissions.append(ResourcePermission.CREATE)
        if actor.can_publish_assistants():
            permissions.append(ResourcePermission.PUBLISH)

        return permissions

    def _get_group_chat_permissions(self, space: Space):
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        permissions = []
        if actor.can_read_group_chats():
            permissions.append(ResourcePermission.READ)
        if actor.can_create_group_chats():
            permissions.append(ResourcePermission.CREATE)
        if actor.can_publish_group_chats():
            permissions.append(ResourcePermission.PUBLISH)

        return permissions

    def _get_app_permissions(self, space: Space):
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions = []

        if actor.can_read_apps():
            permissions.append(ResourcePermission.READ)
        if actor.can_create_apps():
            permissions.append(ResourcePermission.CREATE)
        if actor.can_publish_apps():
            permissions.append(ResourcePermission.PUBLISH)

        return permissions

    def _get_service_permissions(self, space: Space):
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions = []

        if actor.can_read_services():
            permissions.append(ResourcePermission.READ)
        if actor.can_create_services():
            permissions.append(ResourcePermission.CREATE)

        return permissions

    def _get_collection_permissions(self, space: Space):
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions = []

        if actor.can_read_collections():
            permissions.append(ResourcePermission.READ)
        if actor.can_create_collections():
            permissions.append(ResourcePermission.CREATE)

        return permissions

    def _get_website_permissions(self, space: Space):
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions = []

        if actor.can_read_websites():
            permissions.append(ResourcePermission.READ)
        if actor.can_create_websites():
            permissions.append(ResourcePermission.CREATE)

        return permissions

    def _get_integration_knowledge_permissions(self, space: Space):
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions = []

        if actor.can_read_integration_knowledge_list():
            permissions.append(ResourcePermission.READ)
        if actor.can_create_integration_knowledge_list():
            permissions.append(ResourcePermission.CREATE)
        if actor.can_delete_integration_knowledge_list():
            permissions.append(ResourcePermission.DELETE)

        return permissions

    def _get_default_assistant_permissions(self, space: Space):
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions = []

        if actor.can_read_default_assistant():
            permissions.append(ResourcePermission.READ)

        if actor.can_edit_default_assistant():
            permissions.append(ResourcePermission.EDIT)

        return permissions

    def _get_member_permissions(self, space: Space):
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions = []

        if actor.can_read_members():
            permissions.append(ResourcePermission.READ)

        if actor.can_edit_space():
            permissions.extend(
                [
                    ResourcePermission.ADD,
                    ResourcePermission.EDIT,
                    ResourcePermission.REMOVE,
                ]
            )

        return permissions

    def _get_space_permissions(self, space: Space):
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions = []

        if actor.can_read_space():
            permissions.append(ResourcePermission.READ)

        if actor.can_edit_space():
            permissions.append(ResourcePermission.EDIT)

        if actor.can_delete_space():
            permissions.append(ResourcePermission.DELETE)

        return permissions

    def _sort_members(self, space: Space):
        if not space.members:
            return []

        return [space.members[self.user.id]] + [
            member for member in space.members.values() if member.id != self.user.id
        ]

    def _get_assistant_model(self, assistant: "Assistant"):
        return AssistantSparse(
            created_at=assistant.created_at,
            updated_at=assistant.updated_at,
            id=assistant.id,
            name=assistant.name,
            completion_model_kwargs=assistant.completion_model_kwargs,
            logging_enabled=assistant.logging_enabled,
            user_id=assistant.user.id,
            published=assistant.published,
            permissions=assistant.permissions,
            description=assistant.description,
            type="assistant",
            metadata_json=assistant.metadata_json,
        )

    def _get_group_chat_model(self, group_chat: "GroupChat"):
        return GroupChatSparse(
            created_at=group_chat.created_at,
            updated_at=group_chat.updated_at,
            name=group_chat.name,
            id=group_chat.id,
            user_id=group_chat.user_id,
            published=group_chat.published,
            permissions=group_chat.permissions,
            type="group-chat",
            metadata_json=group_chat.metadata_json,
        )

    def _get_applications_model(self, space: Space, only_published: bool = False) -> Applications:
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        return Applications(
            assistants=PaginatedPermissions[AssistantSparse](
                items=[
                    self._get_assistant_model(assistant)
                    for assistant in space.assistants
                    if actor.can_read_assistant(assistant=assistant)
                    and (not only_published or assistant.published)
                ],
                permissions=self._get_assistant_permissions(space),
            ),
            group_chats=PaginatedPermissions[GroupChatSparse](
                items=[
                    self._get_group_chat_model(group_chat=group_chat)
                    for group_chat in space.group_chats
                    if actor.can_read_group_chat(group_chat=group_chat)
                    and (not only_published or group_chat.published)
                ],
                permissions=self._get_group_chat_permissions(space=space),
            ),
            apps=PaginatedPermissions[AppSparse](
                items=[
                    app
                    for app in space.apps
                    if actor.can_read_app(app=app) and (not only_published or app.published)
                ],
                permissions=self._get_app_permissions(space),
            ),
            services=PaginatedPermissions[ServiceSparse](
                items=[service for service in space.services if actor.can_read_services()]
                if not only_published
                else [],
                permissions=self._get_service_permissions(space),
            ),
        )

    def _get_knowledge_model(self, space: Space) -> Knowledge:
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        return Knowledge(
            groups=PaginatedPermissions[CollectionPublic](
                items=(
                    [CollectionPublic.from_domain(collection) for collection in space.collections]
                    if actor.can_read_collections()
                    else []
                ),
                permissions=self._get_collection_permissions(space),
            ),
            websites=PaginatedPermissions[WebsitePublic](
                items=[
                    WebsitePublic.from_domain(website)
                    for website in space.websites
                    if actor.can_read_websites()
                ],
                permissions=self._get_website_permissions(space),
            ),
            integration_knowledge_list=PaginatedPermissions[IntegrationKnowledgePublic](
                items=IntegrationKnowledgeAssembler.to_knowledge_model_list(
                    items=space.integration_knowledge_list
                ),
                permissions=self._get_integration_knowledge_permissions(space),
            ),
        )

    def _get_security_classification_model(self, space: Space):
        return (
            SecurityClassificationPublic.from_domain(space.security_classification)
            if space.security_classification
            else None
        )

    def from_space_to_model(self, space: Space) -> SpacePublic:
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        self._set_permissions_on_resources(space)
        applications = self._get_applications_model(space)
        knowledge = self._get_knowledge_model(space)
        members = PaginatedPermissions[SpaceMember](
            items=self._sort_members(space),
            permissions=self._get_member_permissions(space),
        )
        embedding_models = [
            EmbeddingModelPublic.from_domain(model)
            for model in space.embedding_models
            if model.is_org_enabled
        ]
        completion_models = [
            self.completion_model_assembler.from_completion_model_to_model(completion_model=model)
            for model in space.completion_models
            if model.is_org_enabled
        ]

        transcription_models = [
            TranscriptionModelPublic.from_domain(model)
            for model in space.transcription_models
            if model.is_org_enabled
        ]

        default_assistant = None
        if getattr(space, "default_assistant", None) is not None:
            default_assistant = self.assistant_assembler.from_assistant_to_default_assistant_model(
                space.default_assistant,
                permissions=self._get_default_assistant_permissions(space),
            )
        available_roles = [SpaceRole(value=role) for role in actor.get_available_roles()]
        security_classification = None
        if self.user.tenant.security_enabled:
            security_classification = self._get_security_classification_model(space)

        return SpacePublic(
            created_at=space.created_at,
            updated_at=space.updated_at,
            id=space.id,
            name=space.name,
            description=space.description,
            embedding_models=embedding_models,
            completion_models=completion_models,
            transcription_models=transcription_models,
            default_assistant=default_assistant,
            applications=applications,
            knowledge=knowledge,
            members=members,
            personal=space.is_personal(),
            organization=space.is_organization(),
            permissions=self._get_space_permissions(space),
            available_roles=available_roles,
            security_classification=security_classification,
        )

    def from_space_to_sparse_model(self, space: Space) -> SpaceSparse:
        return SpaceSparse(
            created_at=space.created_at,
            updated_at=space.updated_at,
            id=space.id,
            name=space.name,
            description=space.description,
            personal=space.is_personal(),
            organization=space.is_organization(),
            permissions=self._get_space_permissions(space),
        )

    def from_space_to_dashboard_model(self, space: Space, only_published: bool) -> SpaceDashboard:
        self._set_permissions_on_resources(space)
        applications = self._get_applications_model(space=space, only_published=only_published)

        return SpaceDashboard(
            created_at=space.created_at,
            updated_at=space.updated_at,
            id=space.id,
            name=space.name,
            description=space.description,
            personal=space.is_personal(),
            organization=space.is_organization(),
            permissions=self._get_space_permissions(space),
            applications=applications,
        )

    @staticmethod
    def from_service_to_model(service: Service, permissions: list[ResourcePermission] = None):
        permissions = permissions or []

        # TODO: Look into how we surface permissions to the presentation layer
        return CreateSpaceServiceResponse(
            **service.model_dump(exclude={"permissions"}), permissions=permissions
        )

    def from_security_classification_impact_analysis_to_model(
        self, result: SpaceSecurityClassificationImpactAnalysis
    ) -> UpdateSpaceDryRunResponse:
        space = self.from_space_to_model(result.space)

        return UpdateSpaceDryRunResponse(
            assistants=space.applications.assistants.items,
            group_chats=space.applications.group_chats.items,
            apps=space.applications.apps.items,
            services=space.applications.services.items,
            completion_models=[
                self.completion_model_assembler.from_completion_model_to_model(cm)
                for cm in result.affected_completion_models
            ],
            embedding_models=[
                EmbeddingModelPublic.from_domain(em) for em in result.affected_embedding_models
            ],
            transcription_models=[
                TranscriptionModelPublic.from_domain(tm)
                for tm in result.affected_transcription_models
            ],
        )
