from typing import TYPE_CHECKING, cast

from intric.assistants.api.assistant_models import (
    AssistantSparse,
    AssistantType,
    MCPServerPublicDict,
)
from intric.authentication.auth_models import ResourcePermissions
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
from intric.mcp_servers.presentation.assemblers.mcp_server_assembler import (
    MCPServerAssembler,
)
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
    SpaceGroupMember,
    SpaceMember,
    SpacePublic,
    SpaceRole,
    SpaceRoleValue,
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
    from intric.apps.apps.app import App
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
        super().__init__()
        self.user = user
        self.assistant_assembler = assistant_assembler
        self.completion_model_assembler = completion_model_assembler
        self.actor_manager = actor_manager

    def _set_permissions_on_resources(self, space: Space) -> None:
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        for assistant in space.assistants:
            assistant.permissions = actor.get_assistant_permissions(assistant=assistant)

        for group_chat in space.group_chats or []:
            group_chat.permissions = actor.get_group_chat_permissions(
                group_chat=group_chat
            )

        for app in space.apps:
            app.permissions = actor.get_app_permissions()  # type: ignore[attr-defined]

        for service in space.services:
            service.permissions = actor.get_service_permissions()

        for collection in space.collections:
            collection.permissions = actor.get_collection_permissions()

        for website in space.websites:
            website.permissions = actor.get_website_permissions()

        for knowledge in space.integration_knowledge_list:
            knowledge.permissions = actor.get_integrations_permissions()

    def _get_api_key_resource_permissions(self) -> ResourcePermissions | None:
        """Return the effective fine-grained resource permissions from the API key, if any."""
        key = getattr(self.user, "active_api_key", None)
        if key is None:
            return None
        rp = key.resource_permissions
        if rp is None:
            return None
        if isinstance(rp, dict):
            return ResourcePermissions.model_validate(rp)
        return rp

    @staticmethod
    def _cap_permissions(
        permissions: list[ResourcePermission],
        level: str,
    ) -> list[ResourcePermission]:
        """Filter a permissions list down to what the API key level allows.

        Mapping from resource_permissions level to allowed actions:
          none  → nothing
          read  → READ, INSIGHT_VIEW
          write → READ, CREATE, EDIT, DELETE, PUBLISH, INSIGHT_VIEW
          admin → everything (no filtering)
        """
        if level == "admin":
            return permissions
        if level == "none":
            return []

        if level == "read":
            allowed = {ResourcePermission.READ, ResourcePermission.INSIGHT_VIEW}
        else:  # write
            allowed = {
                ResourcePermission.READ,
                ResourcePermission.CREATE,
                ResourcePermission.EDIT,
                ResourcePermission.DELETE,
                ResourcePermission.PUBLISH,
                ResourcePermission.INSIGHT_VIEW,
            }
        return [p for p in permissions if p in allowed]

    def _apply_api_key_resource_caps(
        self, applications: "Applications", knowledge: "Knowledge"
    ) -> None:
        """Intersect reported permissions with API key resource_permissions.

        Mutates the PaginatedPermissions objects in-place so the response
        only advertises actions the caller can actually perform.
        """
        rp = self._get_api_key_resource_permissions()
        if rp is None:
            return

        cap = self._cap_permissions

        applications.assistants.permissions = cap(
            applications.assistants.permissions, rp.assistants.value
        )
        applications.group_chats.permissions = cap(
            applications.group_chats.permissions, rp.assistants.value
        )
        applications.apps.permissions = cap(
            applications.apps.permissions, rp.apps.value
        )
        applications.services.permissions = cap(
            applications.services.permissions, rp.apps.value
        )

        knowledge.groups.permissions = cap(
            knowledge.groups.permissions, rp.knowledge.value
        )
        knowledge.websites.permissions = cap(
            knowledge.websites.permissions, rp.knowledge.value
        )
        knowledge.integration_knowledge_list.permissions = cap(
            knowledge.integration_knowledge_list.permissions, rp.knowledge.value
        )

        # Also cap per-item permissions
        for assistant in applications.assistants.items:
            assistant.permissions = cap(assistant.permissions, rp.assistants.value)
        for group_chat in applications.group_chats.items:
            group_chat.permissions = cap(group_chat.permissions, rp.assistants.value)
        for app in applications.apps.items:
            app.permissions = cap(app.permissions, rp.apps.value)
        for service in applications.services.items:
            service.permissions = cap(service.permissions, rp.apps.value)

        for collection in knowledge.groups.items:
            if hasattr(collection, "permissions"):
                collection.permissions = cap(collection.permissions, rp.knowledge.value)
        for website in knowledge.websites.items:
            if hasattr(website, "permissions"):
                website.permissions = cap(website.permissions, rp.knowledge.value)

    def _cap_space_permissions(
        self, permissions: list[ResourcePermission]
    ) -> list[ResourcePermission]:
        """Cap space-level permissions using the API key's spaces resource permission."""
        rp = self._get_api_key_resource_permissions()
        if rp is None:
            return permissions
        return self._cap_permissions(permissions, rp.spaces.value)

    def _get_assistant_permissions(self, space: Space) -> list[ResourcePermission]:
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions: list[ResourcePermission] = []

        if actor.can_read_assistants():
            permissions.append(ResourcePermission.READ)
        if actor.can_create_assistants():
            permissions.append(ResourcePermission.CREATE)
        if actor.can_publish_assistants():
            permissions.append(ResourcePermission.PUBLISH)

        return permissions

    def _get_group_chat_permissions(self, space: Space) -> list[ResourcePermission]:
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        permissions: list[ResourcePermission] = []
        if actor.can_read_group_chats():
            permissions.append(ResourcePermission.READ)
        if actor.can_create_group_chats():
            permissions.append(ResourcePermission.CREATE)
        if actor.can_publish_group_chats():
            permissions.append(ResourcePermission.PUBLISH)

        return permissions

    def _get_app_permissions(self, space: Space) -> list[ResourcePermission]:
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions: list[ResourcePermission] = []

        if actor.can_read_apps():
            permissions.append(ResourcePermission.READ)
        if actor.can_create_apps():
            permissions.append(ResourcePermission.CREATE)
        if actor.can_publish_apps():
            permissions.append(ResourcePermission.PUBLISH)

        return permissions

    def _get_service_permissions(self, space: Space) -> list[ResourcePermission]:
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions: list[ResourcePermission] = []

        if actor.can_read_services():
            permissions.append(ResourcePermission.READ)
        if actor.can_create_services():
            permissions.append(ResourcePermission.CREATE)

        return permissions

    def _get_collection_permissions(self, space: Space) -> list[ResourcePermission]:
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions: list[ResourcePermission] = []

        if actor.can_read_collections():
            permissions.append(ResourcePermission.READ)
        if actor.can_create_collections():
            permissions.append(ResourcePermission.CREATE)

        return permissions

    def _get_website_permissions(self, space: Space) -> list[ResourcePermission]:
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions: list[ResourcePermission] = []

        if actor.can_read_websites():
            permissions.append(ResourcePermission.READ)
        if actor.can_create_websites():
            permissions.append(ResourcePermission.CREATE)

        return permissions

    def _get_integration_knowledge_permissions(
        self, space: Space
    ) -> list[ResourcePermission]:
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions: list[ResourcePermission] = []

        if actor.can_read_integrations():
            permissions.append(ResourcePermission.READ)
        if actor.can_create_integrations():
            permissions.append(ResourcePermission.CREATE)
        if actor.can_delete_integrations():
            permissions.append(ResourcePermission.DELETE)

        return permissions

    def _get_default_assistant_permissions(
        self, space: Space
    ) -> list[ResourcePermission]:
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions: list[ResourcePermission] = []

        if actor.can_read_default_assistant():
            permissions.append(ResourcePermission.READ)

        if actor.can_edit_default_assistant():
            permissions.append(ResourcePermission.EDIT)

        return permissions

    def _get_member_permissions(self, space: Space) -> list[ResourcePermission]:
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions: list[ResourcePermission] = []

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

    def _get_group_member_permissions(self, space: Space) -> list[ResourcePermission]:
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions: list[ResourcePermission] = []

        if actor.can_read_group_members():
            permissions.append(ResourcePermission.READ)

        if actor.can_add_group_members():
            permissions.append(ResourcePermission.ADD)

        if actor.can_edit_group_members():
            permissions.append(ResourcePermission.EDIT)

        if actor.can_delete_group_members():
            permissions.append(ResourcePermission.REMOVE)

        return permissions

    def _get_space_permissions(self, space: Space) -> list[ResourcePermission]:
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        permissions: list[ResourcePermission] = []

        if actor.can_read_space():
            permissions.append(ResourcePermission.READ)

        if actor.can_edit_space():
            permissions.append(ResourcePermission.EDIT)

        if actor.can_delete_space():
            permissions.append(ResourcePermission.DELETE)

        return permissions

    def _sort_members(self, space: Space) -> list[SpaceMember]:
        if not space.members:
            return []

        current_user = space.members.get(self.user.id)
        if current_user is None:
            return list(space.members.values())

        return [current_user] + [
            member for member in space.members.values() if member.id != self.user.id
        ]

    def _get_assistant_model(self, assistant: "Assistant") -> AssistantSparse:
        assert assistant.user is not None
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
            type=AssistantType.ASSISTANT,
            metadata_json=assistant.metadata_json,
            icon_id=assistant.icon_id,
            completion_model_id=assistant.completion_model.id
            if assistant.completion_model
            else None,
        )

    def _get_group_chat_model(self, group_chat: "GroupChat") -> GroupChatSparse:
        assert group_chat.created_at is not None
        assert group_chat.updated_at is not None
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
            icon_id=group_chat.icon_id,
        )

    def _get_app_model(self, app: "App") -> AppSparse:
        assert app.id is not None
        return AppSparse(
            created_at=app.created_at,
            updated_at=app.updated_at,
            id=app.id,
            name=app.name,
            description=app.description,
            published=app.published,
            user_id=app.user_id,
            permissions=app.permissions,  # type: ignore[attr-defined]
            icon_id=app.icon_id,
        )

    def _get_applications_model(
        self, space: Space, only_published: bool = False
    ) -> Applications:
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
                    for group_chat in (space.group_chats or [])
                    if actor.can_read_group_chat(group_chat=group_chat)
                    and (not only_published or group_chat.published)
                ],
                permissions=self._get_group_chat_permissions(space=space),
            ),
            apps=PaginatedPermissions[AppSparse](
                items=[
                    self._get_app_model(app)
                    for app in space.apps
                    if actor.can_read_app(app=app)
                    and (not only_published or app.published)
                ],
                permissions=self._get_app_permissions(space),
            ),
            services=PaginatedPermissions[ServiceSparse](
                items=[
                    self._get_service_model(service)
                    for service in space.services
                    if actor.can_read_services()
                ]
                if not only_published
                else [],
                permissions=self._get_service_permissions(space),
            ),
        )

    def _get_service_model(self, service: Service) -> ServiceSparse:
        return ServiceSparse(
            created_at=service.created_at,
            updated_at=service.updated_at,
            id=service.id,
            name=service.name,
            prompt=service.prompt,
            completion_model_kwargs=service.completion_model_kwargs,
            user_id=service.user_id,
            permissions=service.permissions,
        )

    def _get_knowledge_model(self, space: Space) -> Knowledge:
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        return Knowledge(
            groups=PaginatedPermissions[CollectionPublic](
                items=(
                    [
                        CollectionPublic.from_domain(collection)
                        for collection in space.collections
                    ]
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

    def _get_security_classification_model(
        self, space: Space
    ) -> SecurityClassificationPublic | None:
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
        self._apply_api_key_resource_caps(applications, knowledge)
        members = PaginatedPermissions[SpaceMember](
            items=self._sort_members(space),
            permissions=self._cap_space_permissions(
                self._get_member_permissions(space)
            ),
        )
        group_members = PaginatedPermissions[SpaceGroupMember](
            items=list(space.group_members.values()),
            permissions=self._cap_space_permissions(
                self._get_group_member_permissions(space)
            ),
        )
        embedding_models = [
            EmbeddingModelPublic.from_domain(model)
            for model in space.embedding_models
            if model.is_org_enabled
        ]
        completion_models = [
            self.completion_model_assembler.from_completion_model_to_model(
                completion_model=model
            )
            for model in space.completion_models
            if model.is_org_enabled
        ]

        transcription_models = [
            TranscriptionModelPublic.from_domain(model)
            for model in space.transcription_models
            if model.is_org_enabled
        ]

        default_assistant = None
        if space.default_assistant is not None:
            space_default_assistant = space.default_assistant
            da_permissions = self._get_default_assistant_permissions(space)
            rp = self._get_api_key_resource_permissions()
            if rp is not None:
                da_permissions = self._cap_permissions(
                    da_permissions, rp.assistants.value
                )
            default_assistant = (
                self.assistant_assembler.from_assistant_to_default_assistant_model(
                    space_default_assistant,
                    permissions=da_permissions,
                )
            )
        available_roles = [
            SpaceRole(value=cast("SpaceRoleValue", role))
            for role in cast(list[object], actor.get_available_roles())
        ]
        security_classification = None
        if self.user.tenant.security_enabled:
            security_classification = self._get_security_classification_model(space)

        mcp_servers: list[MCPServerPublicDict] = [
            cast(MCPServerPublicDict, MCPServerAssembler.to_dict_with_tools(server))
            for server in space.mcp_servers
        ]

        assert space.id is not None
        return SpacePublic(
            created_at=space.created_at,
            updated_at=space.updated_at,
            id=space.id,
            name=space.name,
            description=space.description,
            embedding_models=embedding_models,
            completion_models=completion_models,
            transcription_models=transcription_models,
            mcp_servers=mcp_servers,
            default_assistant=default_assistant,
            applications=applications,
            knowledge=knowledge,
            members=members,
            group_members=group_members,
            personal=space.is_personal(),
            organization=space.is_organization(),
            permissions=self._cap_space_permissions(self._get_space_permissions(space)),
            available_roles=available_roles,
            security_classification=security_classification,
            data_retention_days=space.data_retention_days,
            icon_id=space.icon_id,
        )

    def from_space_to_sparse_model(
        self, space: Space, include_applications: bool
    ) -> SpaceSparse:
        assert space.id is not None
        space_sparse = SpaceSparse(
            created_at=space.created_at,
            updated_at=space.updated_at,
            id=space.id,
            name=space.name,
            description=space.description,
            personal=space.is_personal(),
            organization=space.is_organization(),
            permissions=self._get_space_permissions(space),
            data_retention_days=space.data_retention_days,
            icon_id=space.icon_id,
        )

        if include_applications:
            self._set_permissions_on_resources(space)
            default_assistant = None
            if space.default_assistant is not None:
                space_default_assistant = space.default_assistant
                default_assistant = (
                    self.assistant_assembler.from_assistant_to_default_assistant_model(
                        space_default_assistant,
                        permissions=self._get_default_assistant_permissions(space),
                    )
                )
            applications = self._get_applications_model(space, only_published=True)
            space_sparse.applications = applications
            space_sparse.default_assistant = default_assistant

        return space_sparse

    def from_space_to_dashboard_model(
        self, space: Space, only_published: bool
    ) -> SpaceDashboard:
        self._set_permissions_on_resources(space)
        applications = self._get_applications_model(
            space=space, only_published=only_published
        )

        default_assistant = None
        if space.default_assistant is not None:
            space_default_assistant = space.default_assistant
            default_assistant = (
                self.assistant_assembler.from_assistant_to_default_assistant_model(
                    space_default_assistant,
                    permissions=self._get_default_assistant_permissions(space),
                )
            )

        assert space.id is not None
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
            default_assistant=default_assistant,
            data_retention_days=space.data_retention_days,
            icon_id=space.icon_id,
        )

    @staticmethod
    def from_service_to_model(
        service: Service, permissions: list[ResourcePermission] | None = None
    ) -> CreateSpaceServiceResponse:
        permissions = permissions or []

        # TODO: Look into how we surface permissions to the presentation layer
        return CreateSpaceServiceResponse(
            **service.model_dump(exclude={"permissions"}), permissions=permissions
        )

    def from_security_classification_impact_analysis_to_model(
        self, result: SpaceSecurityClassificationImpactAnalysis
    ) -> UpdateSpaceDryRunResponse:
        space = self.from_space_to_model(result.space)

        from intric.mcp_servers.presentation.assemblers.mcp_server_assembler import (
            MCPServerAssembler,
        )

        applications = space.applications
        if applications is None:
            applications = Applications(
                assistants=PaginatedPermissions[AssistantSparse](items=[]),
                group_chats=PaginatedPermissions[GroupChatSparse](items=[]),
                apps=PaginatedPermissions[AppSparse](items=[]),
                services=PaginatedPermissions[ServiceSparse](items=[]),
            )

        return UpdateSpaceDryRunResponse(
            assistants=applications.assistants.items,
            group_chats=applications.group_chats.items,
            apps=applications.apps.items,
            services=applications.services.items,
            completion_models=[
                self.completion_model_assembler.from_completion_model_to_model(cm)
                for cm in result.affected_completion_models
            ],
            embedding_models=[
                EmbeddingModelPublic.from_domain(em)
                for em in result.affected_embedding_models
            ],
            transcription_models=[
                TranscriptionModelPublic.from_domain(tm)
                for tm in result.affected_transcription_models
            ],
            mcp_servers=[
                cast(MCPServerPublicDict, MCPServerAssembler.to_dict_with_tools(s))
                for s in result.affected_mcp_servers
            ],
        )
