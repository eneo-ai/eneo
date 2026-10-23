from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar, Union, cast
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from eneo.authentication.api_key_scope_revoker import ApiKeyScopeRevoker
from eneo.authentication.auth_models import ApiKeyScopeType, ApiKeyStateReasonCode
from eneo.completion_models.application.completion_model_crud_service import (
    CompletionModelCRUDService,
)
from eneo.completion_models.domain.completion_model_service import (
    CompletionModelService,
)
from eneo.embedding_models.application.embedding_model_crud_service import (
    EmbeddingModelCRUDService,
)
from eneo.icons.icon_repo import IconRepository
from eneo.main.datetime_utils import datetime_or_utc_min
from eneo.main.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
    UnauthorizedException,
    UniqueException,
)
from eneo.main.logging import get_logger
from eneo.main.models import NOT_PROVIDED, ModelId, NotProvided, is_provided
from eneo.mcp_servers.domain.capabilities import (
    CapabilityPurpose,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    CAPABILITY_PURPOSES,
    GENERAL_PURPOSE,
    MCPServer,
    duplicate_capability_purposes,
    is_capability_purpose,
)
from eneo.roles.permissions import Permission
from eneo.spaces.api.space_models import SpaceGroupMember, SpaceMember, SpaceRoleValue
from eneo.spaces.space import SECURITY_CLASSIFICATION_EXCEPTION_MESSAGE, Space
from eneo.spaces.space_applications_projection import SpaceApplicationsProjection
from eneo.spaces.space_factory import SpaceFactory
from eneo.spaces.space_repo import SpaceRepository
from eneo.spaces.space_update import LinkEdit, SpaceUpdate
from eneo.transcription_models.application.transcription_model_crud_service import (
    TranscriptionModelCRUDService,
)
from eneo.transcription_models.domain.transcription_model_service import (
    TranscriptionModelService,
)
from eneo.transcription_services.repository import (
    TranscriptionServiceConnectionRepository,
)
from eneo.user_groups.user_groups_repo import UserGroupsRepository
from eneo.users.user import UserInDB
from eneo.users.user_repo import UsersRepository

if TYPE_CHECKING:
    from eneo.actors import ActorManager
    from eneo.actors.actors.space_actor import SpaceAccessFacts, SpaceActor
    from eneo.apps import App
    from eneo.assistants.assistant import Assistant
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.embedding_models.domain.embedding_model import EmbeddingModel
    from eneo.group_chat.domain.entities.group_chat import GroupChat
    from eneo.main.models import MCPToolSetting
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.security_classifications.application.security_classification_service import (
        SecurityClassificationService,
    )
    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )
    from eneo.services.service import Service
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )
    from eneo.transcription_services.models import TranscriptionServiceConnection


def _empty_mcp_server_list() -> list["MCPServer"]:
    return []


def _empty_connection_list() -> list["TranscriptionServiceConnection"]:
    return []


Item = TypeVar("Item")


def _link_edit(
    selected: list[Item] | None, shown: Iterable[UUID]
) -> LinkEdit[Item] | None:
    """The edit of one link list, scoped to the ids the space showed.

    ``shown`` is the space's list as loaded for this request: the space factory
    and the space repository own which stored entries it hides, so this reuses
    their rule instead of restating it."""
    if selected is None:
        return None
    return LinkEdit(tuple(selected), frozenset(shown))


def _require_space_read(actor: "SpaceActor") -> None:
    if not actor.can_read_space():
        raise UnauthorizedException(
            "You do not have permission to read this space.",
            code="forbidden_action",
            context={
                "resource_type": "space",
                "action": "read",
                "auth_layer": "domain_policy",
            },
        )


@dataclass(frozen=True)
class SpaceSecurityClassificationImpactAnalysis:
    space: Space
    affected_completion_models: list["CompletionModel"]
    affected_embedding_models: list["EmbeddingModel"]
    affected_transcription_models: list["TranscriptionModel"]
    affected_assistant_ids: frozenset[UUID] = frozenset()
    affected_group_chat_ids: frozenset[UUID] = frozenset()
    affected_app_ids: frozenset[UUID] = frozenset()
    affected_service_ids: frozenset[UUID] = frozenset()
    affected_capabilities: list[CapabilityPurpose] = field(
        default_factory=list[CapabilityPurpose]
    )
    affected_mcp_servers: list[MCPServer] = field(
        default_factory=_empty_mcp_server_list
    )
    affected_transcription_services: list["TranscriptionServiceConnection"] = field(
        default_factory=_empty_connection_list
    )


TENANT_SPACE_NAME = "Organization space"


class SpaceService:
    def __init__(
        self,
        user: UserInDB,
        factory: SpaceFactory,
        repo: SpaceRepository,
        user_repo: UsersRepository,
        user_groups_repo: UserGroupsRepository,
        embedding_model_crud_service: EmbeddingModelCRUDService,
        completion_model_crud_service: CompletionModelCRUDService,
        completion_model_service: CompletionModelService,
        transcription_model_crud_service: TranscriptionModelCRUDService,
        transcription_model_service: TranscriptionModelService,
        actor_manager: "ActorManager",
        security_classification_service: "SecurityClassificationService",
        icon_repo: IconRepository,
        api_key_scope_revoker: ApiKeyScopeRevoker | None = None,
    ):
        super().__init__()
        self.user = user
        self.factory = factory
        self.repo = repo
        self.user_repo = user_repo
        self.user_groups_repo = user_groups_repo
        self.embedding_model_crud_service = embedding_model_crud_service
        self.completion_model_crud_service = completion_model_crud_service
        self.completion_model_service = completion_model_service
        self.transcription_model_crud_service = transcription_model_crud_service
        self.transcription_model_service = transcription_model_service
        self.actor_manager = actor_manager
        self.security_classification_service = security_classification_service
        self.icon_repo = icon_repo
        self.api_key_scope_revoker = api_key_scope_revoker
        self._logger = get_logger(__name__)

    async def is_space_member(self, space_id: UUID, user_id: UUID) -> bool:
        """Check if user is a member of space (index-only lookup)."""
        return await self.repo.is_member(space_id=space_id, user_id=user_id)

    async def resolve_space_id_for_scope(
        self, scope_type: str, scope_id: UUID
    ) -> UUID | None:
        """Resolve a key's scope to its parent space_id.

        Returns space_id directly for space-scoped keys.
        """
        if scope_type in (ApiKeyScopeType.SPACE, ApiKeyScopeType.SPACE.value):
            return scope_id
        return await self.repo.get_space_id_for_resource(
            scope_type=scope_type, resource_id=scope_id
        )

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
            tenant_space_id=getattr(hub, "id", None),
        )

        def _get_latest_model(
            models: Sequence["EmbeddingModel"],
        ) -> "EmbeddingModel | None":
            for model in sorted(
                models,
                key=lambda model: datetime_or_utc_min(model.created_at),
                reverse=True,
            ):
                if model.can_access:
                    return model

        # Set embedding models as only the latest one
        embedding_models = (
            await self.embedding_model_crud_service.get_embedding_models()
        )
        latest_embedding_model = _get_latest_model(embedding_models)
        space.embedding_models = (
            [latest_embedding_model] if latest_embedding_model else []
        )

        # Set completion models
        completion_models = (
            await self.completion_model_service.get_available_completion_models()
        )
        space.completion_models = completion_models

        # Set transcription models as only the default one
        transcription_model = await self.transcription_model_service.get_default_model()

        if transcription_model is None:
            transcription_models = []
        else:
            transcription_models = [transcription_model]

        space.transcription_models = transcription_models

        # A new space offers the capabilities the tenant has a provider for.
        # It has no general MCP server: its admin activates the ones it may use.
        import sqlalchemy as sa

        from eneo.database.tables.mcp_server_table import (
            MCPServers as MCPServersTable,
        )

        query = (
            sa.select(MCPServersTable)
            .where(MCPServersTable.tenant_id == self.user.tenant_id)
            .where(MCPServersTable.is_enabled == True)  # noqa: E712
        )
        result = await self.repo.session.execute(query)
        servers_db = result.scalars().all()

        space.enabled_capabilities = sorted(
            {
                purpose
                for purpose in CAPABILITY_PURPOSES
                if any(s.purpose == purpose for s in servers_db)
            }
        )

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
        _require_space_read(self._get_actor(space))
        return space

    async def get_space_access_facts(self, id: UUID) -> "SpaceAccessFacts":
        """The facts ``get_space``'s caller decides their own permissions on,
        with ``get_space``'s refusals, for a caller that needs nothing else of
        the space: only the caller's membership and key scope are read, never
        the space aggregate (``SpaceRepository.get_space_access_facts``)."""
        access = await self.repo.get_space_access_facts(id)
        _require_space_read(self.actor_manager.get_space_actor(access))
        return access

    async def get_applications_projection(
        self, id: UUID
    ) -> SpaceApplicationsProjection:
        projection = await self.repo.get_applications_projection(id)
        _require_space_read(self.actor_manager.get_space_actor(projection.access))
        return projection

    async def get_member_space_actors(self) -> list["SpaceActor"]:
        """Actors for the readable spaces among those the user belongs to,
        built from membership facts instead of loading each space."""
        actors = [
            self.actor_manager.get_space_actor(access)
            for access in await self.repo.get_member_access_facts()
        ]
        return [actor for actor in actors if actor.can_read_space()]

    async def _validate_capability_markers(
        self,
        mcp_servers: list["MCPServer"],
        space_security_classification: "SecurityClassification | None",
    ) -> None:
        """Reject a capability marker no active provider can serve.

        The marker's own classification is irrelevant (the ask path swaps in
        the provider serving the user), so the check runs against the active
        providers for the purpose: at least one must meet the space's
        classification. Ask time remains the hard guarantee per user.

        Also rejects a second marker for the same purpose: one marker per
        capability is what every surface toggles.
        """
        duplicates = duplicate_capability_purposes(
            server.purpose for server in mcp_servers
        )
        if duplicates:
            raise BadRequestException(
                "Only one MCP server per capability can be attached: "
                + ", ".join(duplicates)
            )
        if space_security_classification is None:
            return
        from eneo.mcp_servers.application.capability_resolver import (
            get_active_capability_servers,
            meets_security_classification,
        )

        for purpose in {
            server.purpose
            for server in mcp_servers
            if is_capability_purpose(server.purpose)
        }:
            providers = await get_active_capability_servers(
                self.repo.session, self.user.tenant_id, purpose
            )
            if providers and not any(
                meets_security_classification(provider, space_security_classification)
                for provider in providers
            ):
                raise BadRequestException(SECURITY_CLASSIFICATION_EXCEPTION_MESSAGE)

    async def update_space(
        self,
        id: UUID,
        name: str | None = None,
        description: str | None = None,
        embedding_model_ids: list[UUID] | None = None,
        completion_model_ids: list[UUID] | None = None,
        transcription_model_ids: list[UUID] | None = None,
        transcription_service_ids: list[UUID] | None = None,
        mcp_server_ids: list[UUID] | None = None,
        enabled_capabilities: list[CapabilityPurpose] | None = None,
        mcp_tools: list["MCPToolSetting"] | None = None,
        security_classification: Union[ModelId, NotProvided, None] = NOT_PROVIDED,
        data_retention_days: Union[int, None, NotProvided] = NOT_PROVIDED,
        icon_id: Union[UUID, None, NotProvided] = NOT_PROVIDED,
    ) -> Space:
        space = await self.get_space(id)
        actor = self._get_actor(space)

        if not actor.can_edit_space():
            raise UnauthorizedException("User does not have permission to edit space")

        space_security_classification = None
        if is_provided(security_classification):
            if not self.user.tenant.security_enabled:
                raise BadRequestException("Security is not enabled for this tenant")
            if security_classification is not None:
                classification_id = security_classification.id
                space_security_classification = await self.security_classification_service.get_security_classification(  # noqa: E501
                    classification_id
                )

        # A model already linked is kept as the space holds it: keeping a link
        # grants no use, so it needs no access lookup, and one the tenant has
        # since disabled, or that fell below the classification, stays linked.
        # Only a new link goes through the access-checked lookup.
        linked_completion = {m.id: m for m in space.linked_completion_models}
        linked_embedding = {m.id: m for m in space.linked_embedding_models}
        linked_transcription = {m.id: m for m in space.linked_transcription_models}
        # Read before ``space.update``, which replaces ``space.mcp_servers``
        # with the selection.
        shown_mcp_servers = [server.id for server in space.mcp_servers]
        shown_mcp_tools = [
            tool.id for server in space.mcp_servers for tool in server.tools
        ]

        completion_models: list["CompletionModel"] | None = None
        if completion_model_ids is not None:
            completion_models = [
                linked_completion.get(model_id)
                or await self.completion_model_crud_service.get_completion_model(
                    model_id=model_id
                )
                for model_id in completion_model_ids
            ]

        embedding_models: list["EmbeddingModel"] | None = None
        if embedding_model_ids is not None:
            embedding_models = []
            for model_id in embedding_model_ids:
                model = linked_embedding.get(model_id) or cast(
                    "EmbeddingModel | None",
                    await self.embedding_model_crud_service.get_embedding_model(
                        model_id
                    ),
                )
                if model:
                    embedding_models.append(model)

        transcription_models: list["TranscriptionModel"] | None = None
        if transcription_model_ids is not None:
            transcription_models = [
                linked_transcription.get(model_id)
                or await self.transcription_model_crud_service.get_transcription_model(
                    model_id=model_id
                )
                for model_id in transcription_model_ids
            ]

        transcription_services: list["TranscriptionServiceConnection"] | None = None
        if transcription_service_ids is not None:
            linked_services = {c.id: c for c in space.linked_transcription_services}
            new_service_ids = [
                connection_id
                for connection_id in transcription_service_ids
                if connection_id not in linked_services
            ]
            found = {
                connection.id: connection
                for connection in await TranscriptionServiceConnectionRepository(
                    self.repo.session, self.user.tenant_id
                ).get_many(new_service_ids)
            }
            transcription_services = [
                linked_services.get(connection_id) or found[connection_id]
                for connection_id in transcription_service_ids
            ]

        mcp_servers: list["MCPServer"] | None = None
        if mcp_server_ids is not None:
            # Query tenant MCP servers directly from database
            import sqlalchemy as sa
            from sqlalchemy.orm import selectinload as _selectinload

            from eneo.database.tables.mcp_server_table import (
                MCPServers as MCPServersTable,
            )
            from eneo.database.tables.security_classifications_table import (
                SecurityClassification as SecurityClassificationDBModel,
            )
            from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
            from eneo.security_classifications.domain.entities.security_classification import (
                SecurityClassification,
            )

            # Capability servers are markers resolved to the active provider
            # at ask time, so a deactivated one may legitimately stay in the
            # space; only general servers must be currently enabled.
            query = (
                sa.select(MCPServersTable)
                .where(MCPServersTable.tenant_id == self.user.tenant_id)
                .where(
                    sa.or_(
                        MCPServersTable.is_enabled == True,  # noqa: E712
                        MCPServersTable.purpose != GENERAL_PURPOSE,
                    )
                )
                .where(MCPServersTable.id.in_(mcp_server_ids))
                .options(
                    _selectinload(MCPServersTable.security_classification).selectinload(
                        SecurityClassificationDBModel.tenant
                    ),
                )
            )
            result = await self.repo.session.execute(query)
            servers_db = result.scalars().all()

            # Validate that all requested servers exist and are enabled
            found_ids = {server.id for server in servers_db}
            for mcp_server_id in mcp_server_ids:
                if mcp_server_id not in found_ids:
                    raise BadRequestException(
                        f"MCP server {mcp_server_id} is not enabled for this tenant"
                    )

            # Convert to domain entities
            mcp_servers = [
                MCPServer(
                    id=server.id,
                    tenant_id=server.tenant_id,
                    name=server.name,
                    description=server.description,
                    http_url=server.http_url,
                    http_auth_type=server.http_auth_type,
                    http_auth_config_schema=server.http_auth_config_schema,
                    purpose=server.purpose,
                    is_enabled=server.is_enabled,
                    env_vars=server.env_vars,
                    tags=server.tags,
                    icon_url=server.icon_url,
                    documentation_url=server.documentation_url,
                    security_classification=SecurityClassification.to_domain(
                        server.security_classification
                    ),
                    created_at=server.created_at,
                    updated_at=server.updated_at,
                )
                for server in servers_db
            ]

        if mcp_servers is not None and any(
            is_capability_purpose(s.purpose) for s in mcp_servers
        ):
            raise BadRequestException(
                "Use enabled_capabilities for functions, not MCP server IDs"
            )
        if enabled_capabilities is not None:
            from eneo.mcp_servers.application.capability_resolver import (
                validate_capability_additions,
            )

            await validate_capability_additions(
                self.repo.session,
                self.user.tenant_id,
                enabled_capabilities,
                space.enabled_capabilities,
                space_security_classification
                if is_provided(security_classification)
                else space.security_classification,
            )
            space.enabled_capabilities = sorted(set(enabled_capabilities))
        if mcp_servers is not None:
            await self._validate_capability_markers(
                mcp_servers,
                space_security_classification
                if is_provided(security_classification)
                else space.security_classification,
            )

        # Read before the update: the stored links follow the domain's rule.
        changes_security_level = is_provided(
            security_classification
        ) and space.changes_security_level(space_security_classification)
        space.update(
            name=name,
            description=description,
            completion_models=completion_models,
            embedding_models=embedding_models,
            transcription_models=transcription_models,
            transcription_services=transcription_services,
            mcp_servers=mcp_servers,
            security_classification=(
                space_security_classification
                if is_provided(security_classification)
                else NOT_PROVIDED
            ),
            data_retention_days=data_retention_days,
            icon_id=icon_id,
        )

        # Convert MCPToolSetting objects to tuples for repository
        mcp_tool_settings: list[tuple[UUID, bool]] | None = None
        if mcp_tools is not None:
            mcp_tool_settings = [(tool.tool_id, tool.is_enabled) for tool in mcp_tools]

        await self.repo.update_settings(
            id,
            SpaceUpdate(
                name=name if name is not None else NOT_PROVIDED,
                description=description if description is not None else NOT_PROVIDED,
                security_classification_id=(
                    space.security_classification.id
                    if space.security_classification
                    else None
                )
                if is_provided(security_classification)
                else NOT_PROVIDED,
                minimum_security_level=(
                    space.security_classification.security_level
                    if changes_security_level
                    and space.security_classification
                    and space.security_classification.security_enabled
                    else None
                ),
                data_retention_days=data_retention_days,
                icon_id=icon_id,
                completion_models=_link_edit(completion_model_ids, linked_completion),
                embedding_models=_link_edit(embedding_model_ids, linked_embedding),
                transcription_models=_link_edit(
                    transcription_model_ids, linked_transcription
                ),
                transcription_service_ids=transcription_service_ids,
                mcp_servers=_link_edit(mcp_server_ids, shown_mcp_servers),
                enabled_capabilities=enabled_capabilities,
                mcp_tools=_link_edit(mcp_tool_settings, shown_mcp_tools),
            ),
        )
        return await self.get_space(id)

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
        # The linked lists: a model already below the classification is
        # removed by the change too, so the preview names it.
        current_completion_models = space.linked_completion_models
        current_embedding_models = space.linked_embedding_models
        current_transcription_models = space.linked_transcription_models
        current_transcription_services = space.linked_transcription_services
        current_mcp_servers = space.mcp_servers

        remaining_completion_model_ids = [
            cm.id
            for cm in space.linked_completion_models
            if not security_classification.is_greater_than(cm.security_classification)
        ]
        remaining_embedding_model_ids = [
            em.id
            for em in space.linked_embedding_models
            if not security_classification.is_greater_than(em.security_classification)
        ]
        remaining_transcription_model_ids = [
            tm.id
            for tm in space.linked_transcription_models
            if not security_classification.is_greater_than(tm.security_classification)
        ]
        remaining_mcp_server_ids = [
            server.id
            for server in space.mcp_servers
            if not security_classification.is_greater_than(
                server.security_classification
            )
        ]
        remaining_service_ids = {
            c.id
            for c in space.linked_transcription_services
            if not security_classification.is_greater_than(c.security_classification)
        }

        affected_completion_models: list["CompletionModel"] = [
            cm
            for cm in current_completion_models
            if cm.id not in remaining_completion_model_ids
        ]
        affected_embedding_models: list["EmbeddingModel"] = [
            em
            for em in current_embedding_models
            if em.id not in remaining_embedding_model_ids
        ]
        affected_transcription_models: list["TranscriptionModel"] = [
            tm
            for tm in current_transcription_models
            if tm.id not in remaining_transcription_model_ids
        ]
        affected_mcp_servers: list["MCPServer"] = [
            s for s in current_mcp_servers if s.id not in remaining_mcp_server_ids
        ]
        affected_transcription_services = [
            c
            for c in current_transcription_services
            if c.id not in remaining_service_ids
        ]

        affected_capabilities: list[CapabilityPurpose] = []
        if space.enabled_capabilities:
            from eneo.mcp_servers.application.capability_resolver import (
                capability_availability,
            )

            previous_available = {
                state.purpose
                for state in space.available_capabilities
                if state.available
            }
            proposed_capabilities = await capability_availability(
                self.repo.session, self.user.tenant_id, security_classification
            )
            affected_capabilities = [
                state.purpose
                for state in proposed_capabilities
                if state.purpose in space.enabled_capabilities
                and state.purpose in previous_available
                and not state.available
            ]

        affected_assistants: list["Assistant"] = []
        all_assistants = (
            [*space.assistants, space.default_assistant]
            if space.default_assistant is not None
            else space.assistants
        )
        for assistant in all_assistants:
            if set(assistant.enabled_capabilities) & set(affected_capabilities):
                affected_assistants.append(assistant)
            if (
                assistant.completion_model is not None
                and assistant.completion_model.id not in remaining_completion_model_ids
            ):
                if assistant not in affected_assistants:
                    affected_assistants.append(assistant)
            if (
                assistant.embedding_model_id is not None
                and assistant.embedding_model_id not in remaining_embedding_model_ids
            ):
                if assistant not in affected_assistants:
                    affected_assistants.append(assistant)

        affected_group_chats: list["GroupChat"] = []
        for group_chat in space.group_chats or []:
            for assistant in group_chat.get_assistants():
                if assistant.id in [a.id for a in affected_assistants]:
                    if group_chat not in affected_group_chats:
                        affected_group_chats.append(group_chat)

        affected_apps: list["App"] = []
        for app in space.apps:
            completion_model = cast("CompletionModel | None", app.completion_model)
            if (
                completion_model is not None
                and completion_model.id not in remaining_completion_model_ids
            ):
                affected_apps.append(app)
            transcription_model = app.transcription_model
            if (
                transcription_model is not None
                and transcription_model.id not in remaining_transcription_model_ids
            ):
                if app not in affected_apps:
                    affected_apps.append(app)

        affected_services: list["Service"] = []
        for service in space.services:
            if (
                service.completion_model is not None
                and service.completion_model.id not in remaining_completion_model_ids
            ):
                affected_services.append(service)
            for group in service.groups:
                embedding_model = getattr(group, "embedding_model", None)
                if (
                    embedding_model
                    and embedding_model.id not in remaining_embedding_model_ids
                ):
                    if service not in affected_services:
                        affected_services.append(service)

        return SpaceSecurityClassificationImpactAnalysis(
            space=space,
            affected_completion_models=affected_completion_models,
            affected_embedding_models=affected_embedding_models,
            affected_transcription_models=affected_transcription_models,
            affected_mcp_servers=affected_mcp_servers,
            affected_capabilities=affected_capabilities,
            affected_transcription_services=affected_transcription_services,
            affected_assistant_ids=frozenset(a.id for a in affected_assistants),
            affected_group_chat_ids=frozenset(c.id for c in affected_group_chats),
            affected_app_ids=frozenset(a.id for a in affected_apps if a.id is not None),
            affected_service_ids=frozenset(s.id for s in affected_services),
        )

    async def delete_space(self, id: UUID):
        space = await self.get_space(id)
        actor = self._get_actor(space)

        if not actor.can_delete_space():
            raise UnauthorizedException("User does not have permission to delete space")

        icon_id = space.icon_id
        assert space.id is not None

        if await self.repo.has_flow_delete_blockers(space.id):
            if await self.repo.has_active_legal_hold(space.id):
                raise ConflictException(
                    "A legal hold on Flow run history in this Space blocks its "
                    "deletion. Release the hold first.",
                    code="space_contains_legal_hold",
                    context={"space_id": str(space.id)},
                )
            raise ConflictException(
                "Space contains Flow history or Flow-owned draft resources. "
                "Remove draft Flows first; spaces with Flow run history require "
                "Flow data purge before deletion.",
                code="space_contains_flow_delete_blockers",
                context={"space_id": str(space.id)},
            )

        await self._revoke_space_api_keys(space)
        await self.repo.delete(space.id)

        if icon_id:
            await self.icon_repo.delete_unused(icon_id, tenant_id=self.user.tenant_id)

    async def _revoke_space_api_keys(self, space: Space) -> None:
        if self.api_key_scope_revoker is None:
            return

        assert space.id is not None

        try:
            await self.api_key_scope_revoker.revoke_scope(
                scope_type=ApiKeyScopeType.SPACE,
                scope_id=space.id,
                reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
                reason_text="Space deleted",
            )
        except Exception:
            self._logger.exception(
                "Failed to revoke API keys for deleted space",
                extra={"space_id": str(space.id)},
            )

        for assistant_id in await self.repo.assistant_ids(space.id):
            try:
                await self.api_key_scope_revoker.revoke_scope(
                    scope_type=ApiKeyScopeType.ASSISTANT,
                    scope_id=assistant_id,
                    reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
                    reason_text="Space deleted",
                )
            except Exception:
                self._logger.exception(
                    "Failed to revoke API keys for assistant in deleted space",
                    extra={
                        "space_id": str(space.id),
                        "assistant_id": str(assistant_id),
                    },
                )

        for app in space.apps:
            assert app.id is not None
            try:
                await self.api_key_scope_revoker.revoke_scope(
                    scope_type=ApiKeyScopeType.APP,
                    scope_id=app.id,
                    reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
                    reason_text="Space deleted",
                )
            except Exception:
                self._logger.exception(
                    "Failed to revoke API keys for app in deleted space",
                    extra={"space_id": str(space.id), "app_id": str(app.id)},
                )

    async def get_spaces(
        self, *, include_personal: bool = False, include_applications: bool = False
    ) -> list[Space]:
        spaces = await self.repo.get_spaces_for_member(
            include_applications=include_applications
        )
        # The organization space belongs to the current admins (SpaceActor); a
        # membership row can outlive the admin role that added it.
        if Permission.ADMIN not in self.user.permissions:
            spaces = [space for space in spaces if not self.is_org_space(space)]

        if include_personal:
            personal_space = await self.get_personal_space()
            if personal_space is not None:
                return [personal_space] + spaces
            return spaces

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
        await self.repo.add_member(id, member)

        return member

    async def remove_member(self, id: UUID, user_id: UUID):
        if user_id == self.user.id:
            raise BadRequestException("Can not remove yourself")

        space = await self.get_space(id)
        actor = self._get_actor(space)

        if not actor.can_edit_space():
            raise UnauthorizedException("Only Admins of the space can remove members")

        space.remove_member(user_id)

        await self.repo.remove_member(id, user_id)

        # Revoke all API keys the removed user owns for this space and its resources
        if self.api_key_scope_revoker is not None:
            app_ids: list[UUID] = []
            for app in space.apps:
                assert app.id is not None
                app_ids.append(app.id)
            revoked = await self.api_key_scope_revoker.revoke_member_keys(
                tenant_id=self.user.tenant_id,
                owner_user_id=user_id,
                space_id=id,
                assistant_ids=await self.repo.assistant_ids(id),
                app_ids=app_ids,
                reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
                reason_text=f"User removed from space {space.name}",
            )
            if revoked:
                self._logger.info(
                    f"Revoked {revoked} API keys for user {user_id} removed from space {id}"
                )

    async def get_space_member(self, space_id: UUID, user_id: UUID) -> SpaceMember:
        """Get a space member by user ID.

        Args:
            space_id: ID of the space
            user_id: ID of the user/member

        Returns:
            SpaceMember object

        Raises:
            NotFoundException: If the user is not a member of the space
        """
        space = await self.get_space(space_id)
        try:
            return space.get_member(user_id)
        except KeyError:
            raise NotFoundException(
                f"User {user_id} is not a member of space {space_id}"
            )

    async def change_role_of_member(
        self, id: UUID, user_id: UUID, new_role: SpaceRoleValue
    ):
        if user_id == self.user.id:
            raise BadRequestException("Can not change role of yourself")

        space = await self.get_space(id)
        actor = self._get_actor(space)

        if not actor.can_edit_space():
            raise UnauthorizedException(
                "Only Admins of the space can change the roles of members"
            )

        space.change_member_role(user_id, new_role)
        await self.repo.change_member_role(id, user_id, new_role)

        return space.get_member(user_id)

    # Group Member Management

    async def add_group_member(
        self, space_id: UUID, group_id: UUID, role: SpaceRoleValue
    ) -> SpaceGroupMember:
        space = await self.get_space(space_id)
        actor = self._get_actor(space)

        if not actor.can_add_group_members():
            raise UnauthorizedException(
                "Only Admins can add group members to the space"
            )

        if space.is_personal():
            raise BadRequestException("Cannot add group members to personal spaces")

        user_group = await self.user_groups_repo.get_user_group(group_id)
        if user_group is None or user_group.tenant_id != self.user.tenant_id:
            raise NotFoundException(f"User group {group_id} not found")

        group_member = SpaceGroupMember(
            id=user_group.id,
            name=user_group.name,
            role=role,
            user_count=len(user_group.users) if user_group.users else 0,
        )

        space.add_group_member(group_member)
        await self.repo.add_group_member(space_id, group_member)

        return group_member

    async def remove_group_member(self, space_id: UUID, group_id: UUID):
        """Remove a user group from a space.

        Args:
            space_id: ID of the space
            group_id: ID of the user group to remove

        Raises:
            UnauthorizedException: If user doesn't have permission to remove group members
            BadRequestException: If group is not a member of the space
        """
        space = await self.get_space(space_id)
        actor = self._get_actor(space)

        if not actor.can_delete_group_members():
            raise UnauthorizedException(
                "Only Admins can remove group members from the space"
            )

        space.remove_group_member(group_id)
        await self.repo.remove_group_member(space_id, group_id)

    async def change_group_member_role(
        self, space_id: UUID, group_id: UUID, new_role: SpaceRoleValue
    ) -> SpaceGroupMember:
        """Change the role of a user group in a space.

        Args:
            space_id: ID of the space
            group_id: ID of the user group
            new_role: New role to assign

        Returns:
            The updated SpaceGroupMember

        Raises:
            UnauthorizedException: If user doesn't have permission to edit group members
            BadRequestException: If group is not a member of the space
        """
        space = await self.get_space(space_id)
        actor = self._get_actor(space)

        if not actor.can_edit_group_members():
            raise UnauthorizedException("Only Admins can change group member roles")

        space.change_group_member_role(group_id, new_role)
        await self.repo.change_group_member_role(space_id, group_id, new_role)

        return space.get_group_member(group_id)

    async def get_group_member(
        self, space_id: UUID, group_id: UUID
    ) -> SpaceGroupMember:
        """Get a group member by ID.

        Args:
            space_id: ID of the space
            group_id: ID of the user group

        Returns:
            SpaceGroupMember object

        Raises:
            NotFoundException: If the group is not a member of the space
        """
        space = await self.get_space(space_id)
        try:
            return space.get_group_member(group_id)
        except KeyError:
            raise NotFoundException(
                f"Group {group_id} is not a member of space {space_id}"
            )

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

    async def get_personal_space(self) -> Space | None:
        return await self.repo.get_personal_space(self.user.id)

    async def _get_space_by_resource(self, space: Space | None) -> Space:
        if space is None:
            raise NotFoundException("Space not found")

        actor = self._get_actor(space)

        if not actor.can_read_space():
            raise UnauthorizedException(
                "You do not have permission to read this space.",
                code="forbidden_action",
                context={
                    "resource_type": "space",
                    "action": "read",
                    "auth_layer": "domain_policy",
                },
            )

        return space

    async def get_space_by_group_chat(self, group_chat_id: UUID) -> Space:
        space = await self.repo.get_space_by_group_chat(group_chat_id=group_chat_id)
        return await self._get_space_by_resource(space)

    async def get_space_by_assistant(self, assistant_id: UUID) -> Space:
        space = await self.repo.get_space_by_assistant(assistant_id=assistant_id)
        return await self._get_space_by_resource(space)

    async def get_space_by_app(self, app_id: UUID) -> Space:
        space = await self.repo.get_space_by_app(app_id=app_id)
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
        """Make the organization space's members exactly the tenant's admins.

        Access there follows the admin permission (SpaceActor), so a former
        admin's row grants nothing; it is removed so the space's members are
        the people who are admins now.
        """
        assert hub.id is not None
        admins = await self.user_repo.list_tenant_admins(self.user.tenant_id)
        admin_ids = {admin.id for admin in admins}
        changed = False
        for u in admins:
            if u.id not in hub.members:
                hub.members[u.id] = SpaceMember(
                    id=u.id,
                    username=u.username,
                    email=u.email,
                    role=SpaceRoleValue.ADMIN,
                )
                await self.repo.add_member(hub.id, hub.members[u.id])
                changed = True
        for former_admin_id in [
            member_id for member_id in hub.members if member_id not in admin_ids
        ]:
            hub.remove_member(former_admin_id)
            await self.repo.remove_member(hub.id, former_admin_id)
            changed = True
        if changed:
            hub = await self.repo.one(hub.id)
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
