from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import raiseload, selectinload
from sqlalchemy.sql.dml import ReturningInsert, ReturningUpdate

from eneo.actors.actors.space_actor import (
    SpaceAccessFacts,
    SpaceRoleFact,
    organization_space_role,
)
from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import Assistant, AssistantOrigin
from eneo.authentication.auth_models import ApiKeyScopeType
from eneo.collections.domain.collection import Collection
from eneo.database.association_writes import (
    replace_association_ids,
    replace_association_values,
)
from eneo.database.database import AsyncSession
from eneo.database.tables.ai_models_table import (
    CompletionModels,
    EmbeddingModels,
    TranscriptionModels,
)
from eneo.database.tables.app_table import Apps, AppsFiles, AppsPrompts
from eneo.database.tables.app_template_table import AppTemplates
from eneo.database.tables.assistant_table import Assistants, AssistantsFiles
from eneo.database.tables.assistant_template_table import AssistantTemplates
from eneo.database.tables.capabilities_table import SpaceCapabilities
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.group_chats_table import (
    GroupChatsTable,
)
from eneo.database.tables.groups_spaces_table import GroupsSpaces
from eneo.database.tables.info_blobs_table import InfoBlobs, active_info_blob_version
from eneo.database.tables.integration_knowledge_spaces_table import (
    IntegrationKnowledgesSpaces,
)
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.integration_table import (
    TenantIntegration as TenantIntegrationDBModel,
)
from eneo.database.tables.integration_table import (
    UserIntegration as UserIntegrationDBModel,
)
from eneo.database.tables.mcp_server_table import (
    MCPServers as MCPServersTable,
)
from eneo.database.tables.mcp_server_table import (
    MCPServerTools as MCPServerToolsTable,
)
from eneo.database.tables.mcp_server_table import (
    MCPServerToolSettings as MCPServerToolSettingsTable,
)
from eneo.database.tables.mcp_server_table import (
    SpacesMCPServers,
    SpacesMCPServerTools,
)
from eneo.database.tables.prompts_table import Prompts, PromptsAssistants
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from eneo.database.tables.service_table import Services
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import (
    Spaces,
    SpacesCompletionModels,
    SpacesEmbeddingModels,
    SpacesTranscriptionModels,
    SpacesUserGroups,
    SpacesUsers,
)
from eneo.database.tables.transcription_services_table import (
    SpacesTranscriptionServiceConnections,
    TranscriptionServiceConnections,
)
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import Users, usergroups_users_table
from eneo.database.tables.websites_spaces_table import WebsitesSpaces
from eneo.database.tables.websites_table import Websites as WebsitesTable
from eneo.files.file_content_loader import FileAttachmentGroup, FileContentLoader
from eneo.files.file_models import File, FileMetadata
from eneo.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge as IntegrationKnowledgeEntity,
)
from eneo.integration.domain.factories.integration_knowledge_factory import (
    IntegrationKnowledgeFactory,
)
from eneo.integration.infrastructure.repo_impl.document_counts import (
    active_document_counts,
)
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UniqueException,
)
from eneo.main.logging import get_logger
from eneo.mcp_servers.domain.entities.mcp_server import GENERAL_PURPOSE
from eneo.mcp_servers.domain.tool_switch import ToolSwitch, tool_switch
from eneo.mcp_servers.infrastructure.mappers.mcp_server_mapper import MCPServerMapper
from eneo.prompts.prompt_factory import PromptFactory
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces.api.space_models import SpaceGroupMember, SpaceMember, SpaceRoleValue
from eneo.spaces.space import Space
from eneo.spaces.space_applications_projection import SpaceApplicationsProjection
from eneo.spaces.space_factory import SpaceFactory
from eneo.spaces.space_flow_delete_blockers import (
    space_has_active_legal_hold,
    space_has_flow_delete_blockers,
)
from eneo.spaces.space_update import LinkEdit, SpaceUpdate
from eneo.spaces.utils.space_utils import effective_space_ids_for
from eneo.transcription_services.repository import (
    TranscriptionServiceConnectionRepository,
)
from eneo.user_groups.user_group import UserGroupState
from eneo.users.user import UserSparse
from eneo.websites.domain.website import Website

logger = get_logger(__name__)


@dataclass(frozen=True)
class AssistantMCPServerProjection:
    space_id: UUID
    assistant_id: UUID
    mcp_servers: "tuple[MCPServer, ...]"


if TYPE_CHECKING:
    from eneo.completion_models.domain.completion_model_repo import (
        CompletionModelRepository,
    )
    from eneo.embedding_models.domain.embedding_model_repo import (
        EmbeddingModelRepository,
    )
    from eneo.info_blobs.info_blob import InfoBlobInDB
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.tenants.tenant import TenantInDB
    from eneo.transcription_models.domain.transcription_model_repo import (
        TranscriptionModelRepository,
    )
    from eneo.transcription_services.models import TranscriptionServiceConnection
    from eneo.users.user import UserInDB
    from eneo.websites.domain.http_auth_credentials import HttpAuthCredentials
    from eneo.websites.infrastructure.http_auth_encryption import (
        HttpAuthEncryptionService,
    )


class HiddenAssistants(Enum):
    """Every hidden assistant of the space, selected without listing ids."""

    ALL = "all"


HiddenAssistantSelection = AbstractSet[UUID] | Literal[HiddenAssistants.ALL]


class SpaceRepositoryTenantMismatchError(ValueError):
    pass


class SpaceRepositoryUserRequiredError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredSpaceToolSetting:
    """A space's own stored switch for one tool, whatever the instance
    admin's switch is."""

    tool_name: str
    mcp_server_id: UUID
    is_enabled: bool


@dataclass(frozen=True)
class KnowledgeSource:
    """One kind of knowledge a space can hold: the table that owns it and the
    association table that distributes it to other spaces.

    A source is visible to a space when the space owns it or it is distributed
    to the space, and a space also sees everything visible to its organization
    space (``effective_space_ids_for``). ``visible_to`` and ``spaces_seeing``
    are the two directions of that one rule, so what a space loads as knowledge
    and what a user may preview from a citation cannot drift apart.

    Read access to a blob through this fallback therefore follows space
    visibility, the reader's space role and the source type's tenant
    permission (``collections`` for collection documents), not their chat or
    assistant permissions: a member of any space that sees the source may
    preview it and fetch its original even if chat is disabled for them.
    Authorization in the source's own space is unchanged, and chat and
    assistants keep their own tenant-permission gates in ``SpaceActor``.
    """

    table: type[CollectionsTable] | type[WebsitesTable] | type[IntegrationKnowledge]
    distribution: (
        type[GroupsSpaces] | type[WebsitesSpaces] | type[IntegrationKnowledgesSpaces]
    )
    # Stored as a column expression, not the mapped attribute: a mapped
    # attribute is a descriptor, so reading it off an instance would type as
    # the Python value instead of the column.
    distribution_source_id: sa.ColumnElement[UUID]

    def visible_to(self, space_ids: Sequence[UUID]) -> sa.ColumnElement[bool]:
        """Sources owned by, or distributed to, one of the spaces."""
        return sa.or_(
            self.table.space_id.in_(space_ids),
            sa.exists(
                sa.select(sa.literal(1))
                .select_from(self.distribution)
                .where(self.distribution_source_id == self.table.id)
                .where(self.distribution.space_id.in_(space_ids))
            ),
        )

    def spaces_seeing(
        self, source_id: UUID, tenant_id: UUID
    ) -> sa.CompoundSelect[tuple[UUID | None]]:
        """Spaces that own the source or have it distributed to them."""
        source_filter = (self.table.id == source_id, self.table.tenant_id == tenant_id)
        return (
            sa.select(self.table.space_id)
            .where(*source_filter)
            .union(
                sa.select(self.distribution.space_id)
                .join(self.table, self.distribution_source_id == self.table.id)
                .where(*source_filter)
            )
        )


COLLECTION_SOURCE = KnowledgeSource(
    CollectionsTable, GroupsSpaces, GroupsSpaces.collection_id.expression
)
WEBSITE_SOURCE = KnowledgeSource(
    WebsitesTable, WebsitesSpaces, WebsitesSpaces.website_id.expression
)
INTEGRATION_KNOWLEDGE_SOURCE = KnowledgeSource(
    IntegrationKnowledge,
    IntegrationKnowledgesSpaces,
    IntegrationKnowledgesSpaces.integration_knowledge_id.expression,
)


# id, tenant_id, user_id, tenant_space_id: what access facts need of a space.
_SpaceRow = tuple[UUID, UUID, UUID | None, UUID | None]


def _select_space_rows() -> sa.Select[_SpaceRow]:
    return sa.select(
        Spaces.id, Spaces.tenant_id, Spaces.user_id, Spaces.tenant_space_id
    )


def knowledge_source_for(info_blob: "InfoBlobInDB") -> tuple[KnowledgeSource, UUID]:
    """The source an info blob belongs to and that source's id."""
    if info_blob.group_id is not None:
        return COLLECTION_SOURCE, info_blob.group_id
    if info_blob.website_id is not None:
        return WEBSITE_SOURCE, info_blob.website_id
    if info_blob.integration_knowledge_id is not None:
        return INTEGRATION_KNOWLEDGE_SOURCE, info_blob.integration_knowledge_id
    raise ValueError("InfoBlob missing scope reference")


class SpaceRepository:
    def __init__(
        self,
        *,
        session: AsyncSession,
        tenant: "TenantInDB",
        factory: SpaceFactory,
        file_content_loader: FileContentLoader,
        completion_model_repo: "CompletionModelRepository",
        transcription_model_repo: "TranscriptionModelRepository",
        embedding_model_repo: "EmbeddingModelRepository",
        http_auth_encryption: "HttpAuthEncryptionService",
        user: "UserInDB | None" = None,
    ):
        super().__init__()
        if user is not None and user.tenant_id != tenant.id:
            raise SpaceRepositoryTenantMismatchError(
                "SpaceRepository user tenant does not match repository tenant."
            )
        self.session = session
        self.tenant = tenant
        self.tenant_id = tenant.id
        self.user = user
        self.factory = factory
        self.file_content_loader = file_content_loader
        self.completion_model_repo = completion_model_repo
        self.transcription_model_repo = transcription_model_repo
        self.embedding_model_repo = embedding_model_repo
        self.http_auth_encryption = http_auth_encryption

    def _require_user(self) -> "UserInDB":
        if self.user is None:
            raise SpaceRepositoryUserRequiredError(
                "SpaceRepository operation requires a user-scoped repository."
            )
        return self.user

    async def _load_application_attachments(
        self,
        *,
        tenant_id: UUID,
        assistants: Sequence[Assistants],
        apps: Sequence[Apps],
    ) -> tuple[dict[UUID, list[File]], dict[UUID, list[File]]]:
        groups = [
            FileAttachmentGroup(
                owner_kind=owner_kind,
                owner_id=record.id,
                tenant_id=tenant_id,
                files=tuple(
                    FileMetadata.model_validate(attachment.file)
                    for attachment in record.attachments
                ),
            )
            for owner_kind, records in (
                ("assistant", assistants),
                ("app", apps),
            )
            for record in records
        ]
        loaded = await self.file_content_loader.load_attachment_groups(groups)
        return (
            {record.id: loaded[("assistant", record.id)] for record in assistants},
            {record.id: loaded[("app", record.id)] for record in apps},
        )

    def _options(self) -> list[Any]:
        return [
            selectinload(Spaces.members).selectinload(SpacesUsers.user),
            selectinload(Spaces.group_members)
            .selectinload(SpacesUserGroups.user_group)
            .selectinload(UserGroups.users),
            selectinload(Spaces.services).selectinload(Services.user),
            selectinload(Spaces.integration_knowledge_list).selectinload(
                IntegrationKnowledge.embedding_model
            ),
            selectinload(Spaces.integration_knowledge_list)
            .selectinload(IntegrationKnowledge.user_integration)
            .selectinload(UserIntegrationDBModel.tenant_integration)
            .selectinload(TenantIntegrationDBModel.integration),
            selectinload(Spaces.integration_knowledge_list).selectinload(
                IntegrationKnowledge.sharepoint_subscription
            ),
            selectinload(Spaces.completion_models_mapping),
            selectinload(Spaces.embedding_models_mapping),
            selectinload(Spaces.transcription_models_mapping),
            selectinload(Spaces.transcription_service_connections_mapping),
            selectinload(Spaces.mcp_servers_mapping),
            selectinload(Spaces.security_classification),
            selectinload(Spaces.security_classification).selectinload(
                SecurityClassificationDBModel.tenant
            ),
        ]

    async def is_member(self, space_id: UUID, user_id: UUID) -> bool:
        """Check if user is a member of space (index-only lookup)."""
        query = (
            sa.select(sa.literal(1))
            .select_from(SpacesUsers)
            .where(
                SpacesUsers.space_id == space_id,
                SpacesUsers.user_id == user_id,
            )
            .limit(1)
        )
        return await self.session.scalar(query) is not None

    async def get_space_id_for_resource(
        self, scope_type: str, resource_id: UUID
    ) -> UUID | None:
        """Single indexed lookup: assistant/app -> space_id."""
        from eneo.authentication.auth_models import ApiKeyScopeType

        if scope_type in (ApiKeyScopeType.ASSISTANT, ApiKeyScopeType.ASSISTANT.value):
            query = sa.select(Assistants.space_id).where(Assistants.id == resource_id)
        elif scope_type in (ApiKeyScopeType.APP, ApiKeyScopeType.APP.value):
            query = sa.select(Apps.space_id).where(Apps.id == resource_id)
        else:
            return None
        return await self.session.scalar(query)

    async def get_space_id_for_scope(
        self, scope_type: str, scope_id: UUID
    ) -> UUID | None:
        """Resolve a key's scope to its parent space_id.

        Returns scope_id directly for space-scoped keys,
        looks up the parent space for assistant/app-scoped keys.
        """
        from eneo.authentication.auth_models import ApiKeyScopeType

        if scope_type in (ApiKeyScopeType.SPACE, ApiKeyScopeType.SPACE.value):
            return scope_id
        return await self.get_space_id_for_resource(
            scope_type=scope_type, resource_id=scope_id
        )

    async def _get_collections(
        self, space_ids: list[UUID]
    ) -> Sequence[tuple[CollectionsTable, int]]:
        c = CollectionsTable
        ib = InfoBlobs

        ib_count_sq = (
            sa.select(sa.func.count(sa.distinct(ib.id)))
            .where(ib.group_id == c.id, active_info_blob_version())
            .correlate(c)
            .scalar_subquery()
        )

        stmt = (
            sa.select(
                c,
                sa.func.coalesce(ib_count_sq, 0).label("infoblob_count"),
            )
            .where(COLLECTION_SOURCE.visible_to(space_ids))
            .order_by(c.created_at)
            .options(selectinload(c.embedding_model))
        )

        res = await self.session.execute(stmt)
        rows = res.all()
        # Row[Tuple[CollectionsTable, int]] is structurally a tuple but not a subtype;
        # unpack explicitly so pyright sees tuple[CollectionsTable, int].
        return [(row[0], row[1]) for row in rows]

    async def lock(self, space_id: UUID) -> None:
        """Serialize related settings/membership writes within the caller's transaction."""
        found = await self.session.scalar(
            sa.select(Spaces.id)
            .where(Spaces.id == space_id, Spaces.tenant_id == self.tenant_id)
            .with_for_update()
        )
        if found is None:
            raise NotFoundException("Space not found")

    async def add_member(self, space_id: UUID, member: SpaceMember) -> None:
        await self.lock(space_id)
        await self.session.execute(
            pg_insert(SpacesUsers)
            .values(space_id=space_id, user_id=member.id, role=member.role.value)
            .on_conflict_do_nothing()
        )

    async def remove_member(self, space_id: UUID, user_id: UUID) -> None:
        await self.lock(space_id)
        await self.session.execute(
            sa.delete(SpacesUsers).where(
                SpacesUsers.space_id == space_id, SpacesUsers.user_id == user_id
            )
        )

    async def change_member_role(
        self, space_id: UUID, user_id: UUID, role: SpaceRoleValue
    ) -> None:
        await self.lock(space_id)
        await self.session.execute(
            sa.update(SpacesUsers)
            .where(SpacesUsers.space_id == space_id, SpacesUsers.user_id == user_id)
            .values(role=role.value)
        )

    async def add_group_member(self, space_id: UUID, member: SpaceGroupMember) -> None:
        await self.lock(space_id)
        await self.session.execute(
            pg_insert(SpacesUserGroups)
            .values(space_id=space_id, user_group_id=member.id, role=member.role.value)
            .on_conflict_do_nothing()
        )

    async def remove_group_member(self, space_id: UUID, group_id: UUID) -> None:
        await self.lock(space_id)
        await self.session.execute(
            sa.delete(SpacesUserGroups).where(
                SpacesUserGroups.space_id == space_id,
                SpacesUserGroups.user_group_id == group_id,
            )
        )

    async def change_group_member_role(
        self, space_id: UUID, group_id: UUID, role: SpaceRoleValue
    ) -> None:
        await self.lock(space_id)
        await self.session.execute(
            sa.update(SpacesUserGroups)
            .where(
                SpacesUserGroups.space_id == space_id,
                SpacesUserGroups.user_group_id == group_id,
            )
            .values(role=role.value)
        )

    async def enable_completion_model(self, space_id: UUID, model_id: UUID) -> None:
        await self.lock(space_id)
        await self.session.execute(
            pg_insert(SpacesCompletionModels)
            .values(space_id=space_id, completion_model_id=model_id)
            .on_conflict_do_nothing()
        )

    async def update_settings(self, space_id: UUID, change: SpaceUpdate) -> None:
        await self.lock(space_id)
        values = change.scalar_values()
        if values:
            await self.session.execute(
                sa.update(Spaces).where(Spaces.id == space_id).values(**values)
            )
        if change.completion_models is not None:
            await replace_association_ids(
                self.session,
                SpacesCompletionModels,
                SpacesCompletionModels.space_id,
                space_id,
                SpacesCompletionModels.completion_model_id,
                change.completion_models.selected,
                within=change.completion_models.shown,
            )
        if change.embedding_models is not None:
            await replace_association_ids(
                self.session,
                SpacesEmbeddingModels,
                SpacesEmbeddingModels.space_id,
                space_id,
                SpacesEmbeddingModels.embedding_model_id,
                change.embedding_models.selected,
                within=change.embedding_models.shown,
            )
        if change.transcription_models is not None:
            await replace_association_ids(
                self.session,
                SpacesTranscriptionModels,
                SpacesTranscriptionModels.space_id,
                space_id,
                SpacesTranscriptionModels.transcription_model_id,
                change.transcription_models.selected,
                within=change.transcription_models.shown,
            )
        if change.transcription_service_ids is not None:
            await replace_association_ids(
                self.session,
                SpacesTranscriptionServiceConnections,
                SpacesTranscriptionServiceConnections.space_id,
                space_id,
                SpacesTranscriptionServiceConnections.connection_id,
                change.transcription_service_ids,
            )
        if change.mcp_servers is not None:
            await replace_association_ids(
                self.session,
                SpacesMCPServers,
                SpacesMCPServers.space_id,
                space_id,
                SpacesMCPServers.mcp_server_id,
                change.mcp_servers.selected,
                within=change.mcp_servers.shown,
            )
        if change.enabled_capabilities is not None:
            await replace_association_ids(
                self.session,
                SpaceCapabilities,
                SpaceCapabilities.space_id,
                space_id,
                SpaceCapabilities.purpose,
                change.enabled_capabilities,
            )
        if change.minimum_security_level is not None:
            compatible = sa.select(SecurityClassificationDBModel.id).where(
                SecurityClassificationDBModel.tenant_id == self.tenant_id,
                SecurityClassificationDBModel.security_level
                >= change.minimum_security_level,
            )
            for mapping, target, model in (
                (
                    SpacesCompletionModels,
                    SpacesCompletionModels.completion_model_id,
                    CompletionModels,
                ),
                (
                    SpacesEmbeddingModels,
                    SpacesEmbeddingModels.embedding_model_id,
                    EmbeddingModels,
                ),
                (
                    SpacesTranscriptionModels,
                    SpacesTranscriptionModels.transcription_model_id,
                    TranscriptionModels,
                ),
                (
                    SpacesTranscriptionServiceConnections,
                    SpacesTranscriptionServiceConnections.connection_id,
                    TranscriptionServiceConnections,
                ),
                (SpacesMCPServers, SpacesMCPServers.mcp_server_id, MCPServersTable),
            ):
                incompatible = sa.select(model.id).where(
                    sa.or_(
                        model.security_classification_id.is_(None),
                        model.security_classification_id.not_in(compatible),
                    )
                )
                if model is MCPServersTable:
                    # Function markers are governed through the resolved
                    # provider; preserve the domain's classification rule.
                    incompatible = incompatible.where(
                        MCPServersTable.purpose == "general"
                    )
                await self.session.execute(
                    sa.delete(mapping).where(
                        mapping.space_id == space_id,
                        target.in_(incompatible),
                    )
                )
        if change.mcp_tools is not None:
            switches = dict(change.mcp_tools.selected)
            selected_servers = sa.select(SpacesMCPServers.mcp_server_id).where(
                SpacesMCPServers.space_id == space_id
            )
            valid = set(
                await self.session.scalars(
                    sa.select(MCPServerToolsTable.id).where(
                        MCPServerToolsTable.mcp_server_id.in_(selected_servers),
                        MCPServerToolsTable.id.in_(list(switches)),
                    )
                )
            )
            if switches.keys() - valid:
                raise BadRequestException(
                    "Tool is not assigned to the space's MCP servers"
                )
            await replace_association_values(
                self.session,
                SpacesMCPServerTools,
                SpacesMCPServerTools.space_id,
                space_id,
                SpacesMCPServerTools.mcp_server_tool_id,
                SpacesMCPServerTools.is_enabled,
                switches,
                within=change.mcp_tools.shown,
            )

    async def get_stored_tool_settings(
        self, space_id: UUID
    ) -> dict[UUID, StoredSpaceToolSetting]:
        """The tool switches the space has stored, by tool id, as
        ``update_settings`` wrote them: also those of a tool the instance admin
        switched off for all, which the space's tool list does not show."""
        rows = await self.session.execute(
            sa.select(
                SpacesMCPServerTools.mcp_server_tool_id,
                MCPServerToolsTable.name,
                MCPServerToolsTable.mcp_server_id,
                SpacesMCPServerTools.is_enabled,
            )
            .join(
                MCPServerToolsTable,
                MCPServerToolsTable.id == SpacesMCPServerTools.mcp_server_tool_id,
            )
            .where(SpacesMCPServerTools.space_id == space_id)
        )
        return {
            tool_id: StoredSpaceToolSetting(
                tool_name=name, mcp_server_id=server_id, is_enabled=is_enabled
            )
            for tool_id, name, server_id, is_enabled in rows.tuples()
        }

    async def _load_assistant_mcp_server_tools_with_overrides(
        self,
        space_id: UUID,
        assistant_id: UUID,
        mcp_servers: list["MCPServer"],
        assistant_tool_overrides: dict[UUID, bool] | None = None,
    ) -> list["MCPServer"]:
        """Load the tools of an assistant's MCP servers, each on or off for the assistant.

        Only tools that are on for the space (``tool_switch``: the instance
        admin's switch, then the space's) are returned; of those, a tool is on
        when the assistant switched it on (assistant_mcp_server_tools).
        """
        from eneo.database.tables.assistant_table import AssistantMCPServerTools

        if not mcp_servers:
            return mcp_servers

        mcp_server_ids = [server.id for server in mcp_servers]

        # Load all tools for these servers
        tools_query = (
            sa.select(MCPServerToolsTable)
            .where(MCPServerToolsTable.mcp_server_id.in_(mcp_server_ids))
            .order_by(MCPServerToolsTable.name)
        )
        tools_result = await self.session.execute(tools_query)
        tools_db: list[MCPServerToolsTable] = list(tools_result.scalars().all())

        # Load tenant-level tool settings
        tenant_tool_settings_query = sa.select(MCPServerToolSettingsTable).where(
            MCPServerToolSettingsTable.tenant_id == self.tenant_id
        )
        tenant_settings_result = await self.session.execute(tenant_tool_settings_query)
        tenant_settings_db: list[MCPServerToolSettingsTable] = list(
            tenant_settings_result.scalars().all()
        )

        # Create map: tool_id -> is_enabled (tenant level)
        tenant_tool_settings: dict[UUID, bool] = {
            setting.mcp_server_tool_id: setting.is_enabled
            for setting in tenant_settings_db
        }

        # Load space-level tool overrides
        space_overrides_query = sa.select(SpacesMCPServerTools).where(
            SpacesMCPServerTools.space_id == space_id
        )
        space_overrides_result = await self.session.execute(space_overrides_query)
        space_overrides_db = space_overrides_result.scalars().all()

        # Create map: tool_id -> is_enabled (space level)
        space_tool_overrides = {
            override.mcp_server_tool_id: override.is_enabled
            for override in space_overrides_db
        }

        if assistant_tool_overrides is None:
            assistant_overrides_query = sa.select(AssistantMCPServerTools).where(
                AssistantMCPServerTools.assistant_id == assistant_id
            )
            assistant_overrides_result = await self.session.execute(
                assistant_overrides_query
            )
            assistant_overrides_db = assistant_overrides_result.scalars().all()
            assistant_tool_overrides = {
                override.mcp_server_tool_id: override.is_enabled
                for override in assistant_overrides_db
            }

        return self._project_assistant_mcp_server_tools(
            mcp_servers=mcp_servers,
            tools_db=tools_db,
            tenant_tool_settings=tenant_tool_settings,
            space_tool_overrides=space_tool_overrides,
            assistant_tool_overrides=assistant_tool_overrides,
        )

    @staticmethod
    def _project_assistant_mcp_server_tools(
        *,
        mcp_servers: list["MCPServer"],
        tools_db: Sequence[MCPServerToolsTable],
        tenant_tool_settings: dict[UUID, bool],
        space_tool_overrides: dict[UUID, bool],
        assistant_tool_overrides: dict[UUID, bool],
    ) -> list["MCPServer"]:
        """Apply the canonical tenant, Space and Assistant tool hierarchy."""
        from collections import defaultdict

        from eneo.mcp_servers.domain.entities.mcp_server import MCPServerTool

        tools_by_server: defaultdict[UUID, list[MCPServerTool]] = defaultdict(list)
        for tool_db in tools_db:
            # An assistant is offered only the tools that are on for its space.
            if (
                tool_switch(
                    enabled_by_default=tool_db.is_enabled_by_default,
                    tenant_setting=tenant_tool_settings.get(tool_db.id),
                    space_override=space_tool_overrides.get(tool_db.id),
                )
                is not ToolSwitch.ON
            ):
                continue

            # Of those, a tool is off until the assistant switches it on.
            is_enabled = assistant_tool_overrides.get(tool_db.id, False)

            tool = MCPServerTool(
                id=tool_db.id,
                mcp_server_id=tool_db.mcp_server_id,
                name=tool_db.name,
                title=tool_db.title,
                display_name=tool_db.display_name,
                description=tool_db.description,
                input_schema=tool_db.input_schema,
                meta=tool_db.meta,
                ui_resource_sha256=tool_db.ui_resource_sha256,
                is_enabled_by_default=tool_db.is_enabled_by_default,
                enabled_override=is_enabled,
                # The proxy hides a tool by its review state, so it travels with it.
                requires_approval=tool_db.requires_approval,
                removed_from_remote=tool_db.removed_from_remote,
                created_at=tool_db.created_at,
                updated_at=tool_db.updated_at,
            )
            tools_by_server[tool_db.mcp_server_id].append(tool)

        # Attach tools to servers
        for server in mcp_servers:
            server.tools = tools_by_server.get(server.id, [])

        return mcp_servers

    async def project_assistants_mcp_servers(
        self,
        projections: Sequence[AssistantMCPServerProjection],
    ) -> dict[UUID, list["MCPServer"]]:
        """Project several Assistants with one bounded set of policy reads."""
        from eneo.database.tables.assistant_table import AssistantMCPServerTools

        if not projections:
            return {}

        server_ids = {
            server.id for projection in projections for server in projection.mcp_servers
        }
        if not server_ids:
            return {projection.assistant_id: [] for projection in projections}

        tools_result = await self.session.execute(
            sa.select(MCPServerToolsTable)
            .where(MCPServerToolsTable.mcp_server_id.in_(server_ids))
            .order_by(MCPServerToolsTable.name)
        )
        tools_db: list[MCPServerToolsTable] = list(tools_result.scalars().all())
        tool_ids = {tool.id for tool in tools_db}

        tenant_settings_result = await self.session.execute(
            sa.select(MCPServerToolSettingsTable).where(
                MCPServerToolSettingsTable.tenant_id == self.tenant_id,
                MCPServerToolSettingsTable.mcp_server_tool_id.in_(tool_ids),
            )
        )
        tenant_tool_settings = {
            setting.mcp_server_tool_id: setting.is_enabled
            for setting in tenant_settings_result.scalars().all()
        }

        space_ids = {projection.space_id for projection in projections}
        space_overrides_result = await self.session.execute(
            sa.select(SpacesMCPServerTools).where(
                SpacesMCPServerTools.space_id.in_(space_ids),
                SpacesMCPServerTools.mcp_server_tool_id.in_(tool_ids),
            )
        )
        space_tool_overrides: dict[UUID, dict[UUID, bool]] = {}
        for override in space_overrides_result.scalars().all():
            space_tool_overrides.setdefault(override.space_id, {})[
                override.mcp_server_tool_id
            ] = override.is_enabled

        assistant_ids = {projection.assistant_id for projection in projections}
        assistant_overrides_result = await self.session.execute(
            sa.select(AssistantMCPServerTools).where(
                AssistantMCPServerTools.assistant_id.in_(assistant_ids),
                AssistantMCPServerTools.mcp_server_tool_id.in_(tool_ids),
            )
        )
        assistant_tool_overrides: dict[UUID, dict[UUID, bool]] = {}
        for override in assistant_overrides_result.scalars().all():
            assistant_tool_overrides.setdefault(override.assistant_id, {})[
                override.mcp_server_tool_id
            ] = override.is_enabled

        # Each assistant is projected over its own servers' rows only, so the
        # work stays the size of what it returns, not assistants x catalog.
        tools_by_server: dict[UUID, list[MCPServerToolsTable]] = {}
        for tool in tools_db:
            tools_by_server.setdefault(tool.mcp_server_id, []).append(tool)

        return {
            projection.assistant_id: self._project_assistant_mcp_server_tools(
                mcp_servers=deepcopy(list(projection.mcp_servers)),
                tools_db=[
                    tool
                    for server_id in dict.fromkeys(
                        server.id for server in projection.mcp_servers
                    )
                    for tool in tools_by_server.get(server_id, ())
                ],
                tenant_tool_settings=tenant_tool_settings,
                space_tool_overrides=space_tool_overrides.get(projection.space_id, {}),
                assistant_tool_overrides=assistant_tool_overrides.get(
                    projection.assistant_id, {}
                ),
            )
            for projection in projections
        }

    async def project_assistant_mcp_servers(
        self,
        *,
        space_id: UUID,
        assistant_id: UUID,
        mcp_servers: list["MCPServer"],
        tool_settings: list[tuple[UUID, bool]] | None = None,
    ) -> list["MCPServer"]:
        """Project staged assistant tool settings through the canonical policy.

        Copies the read-model entities because tool projection is intentionally
        mutable and save-time validation must not alter the loaded Space.
        """
        return await self._load_assistant_mcp_server_tools_with_overrides(
            space_id=space_id,
            assistant_id=assistant_id,
            mcp_servers=deepcopy(mcp_servers),
            assistant_tool_overrides=(
                dict(tool_settings) if tool_settings is not None else None
            ),
        )

    async def _get_assistants(
        self,
        space_id: UUID,
        *,
        hidden_assistant_ids: HiddenAssistantSelection = frozenset(),
    ) -> Sequence[Assistants]:
        """The space's assistants, their MCP servers with their tools."""
        stmt = (
            sa.select(Assistants)
            .execution_options(populate_existing=True)
            .where(Assistants.space_id == space_id)
            .options(
                selectinload(Assistants.assistant_websites),
                selectinload(Assistants.assistant_groups),
                selectinload(Assistants.assistant_integration_knowledge),
                selectinload(Assistants.attachments).selectinload(AssistantsFiles.file),
                selectinload(Assistants.template).selectinload(
                    AssistantTemplates.completion_model
                ),
                selectinload(Assistants.mcp_servers),
                selectinload(Assistants.assistant_mcp_server_tools),
            )
            .order_by(Assistants.created_at)
        )
        if hidden_assistant_ids is not HiddenAssistants.ALL:
            stmt = stmt.where(
                sa.or_(
                    Assistants.hidden.is_(False),
                    Assistants.id.in_(hidden_assistant_ids),
                )
                if hidden_assistant_ids
                else Assistants.hidden.is_(False)
            )
        assistant_records = await self.session.execute(stmt)
        assistants = assistant_records.scalars().all()

        assistant_ids = [assistant.id for assistant in assistants]
        stmt = (
            sa.select(Prompts, PromptsAssistants.assistant_id)
            .join(PromptsAssistants)
            .where(PromptsAssistants.prompt_id == Prompts.id)
            .where(PromptsAssistants.assistant_id.in_(assistant_ids))
            .where(PromptsAssistants.is_selected)
            .options(selectinload(Prompts.user))
        )
        prompt_records = await self.session.execute(stmt)
        # One index, first row per assistant wins: matching per assistant by
        # scanning every row made each hidden-inclusive space load quadratic.
        prompt_by_assistant_id: dict[UUID, Prompts] = {}
        for prompt, assistant_id in prompt_records.all():
            prompt_by_assistant_id.setdefault(assistant_id, prompt)

        for assistant in assistants:
            assistant.prompt = prompt_by_assistant_id.get(assistant.id)  # type: ignore[attr-defined]

        # Each assistant's MCP servers with their tools, switched by the space
        # and by that assistant, projected for all assistants in one pass.
        with_mcp_servers = [
            assistant for assistant in assistants if assistant.mcp_servers
        ]
        projected = await self.project_assistants_mcp_servers(
            [
                AssistantMCPServerProjection(
                    space_id=space_id,
                    assistant_id=assistant.id,
                    mcp_servers=tuple(
                        MCPServerMapper.to_entities(assistant.mcp_servers)
                    ),
                )
                for assistant in with_mcp_servers
            ]
        )
        for assistant in with_mcp_servers:
            # The factory takes these in place of the unfiltered relationship.
            setattr(assistant, "_mcp_server_entities", projected[assistant.id])

        return assistants

    async def _get_services(self, space_id: UUID) -> Sequence[Services]:
        # Fetch all services for the space
        stmt = (
            sa.select(Services)
            .execution_options(populate_existing=True)
            .where(Services.space_id == space_id)
            .options(
                selectinload(Services.service_groups),
                selectinload(Services.user),
                selectinload(Services.completion_model),
            )
        )

        service_records = await self.session.execute(stmt)
        services_db = service_records.scalars().all()

        return services_db

    async def _get_group_chats(self, space_id: UUID) -> Sequence[GroupChatsTable]:
        # Fetch all group chats for the space
        stmt = (
            sa.select(GroupChatsTable)
            .execution_options(populate_existing=True)
            .where(GroupChatsTable.space_id == space_id)
            .options(selectinload(GroupChatsTable.group_chat_assistants))
        )

        group_chat_records = await self.session.execute(stmt)
        group_chats_db = group_chat_records.scalars().all()

        return group_chats_db

    def _decrypt_website_auth(
        self, website_record: WebsitesTable
    ) -> "Optional[HttpAuthCredentials]":
        """Decrypt HTTP auth credentials from database record.

        Why: Repository is the encryption boundary - domain gets clean objects.

        Returns:
            HttpAuthCredentials if auth present and decryption succeeds, None otherwise.
        """

        if not (
            website_record.http_auth_username
            and website_record.encrypted_auth_password
            and website_record.http_auth_domain
        ):
            return None

        try:
            return self.http_auth_encryption.decrypt_credentials(
                username=website_record.http_auth_username,
                encrypted_password=website_record.encrypted_auth_password,
                auth_domain=website_record.http_auth_domain,
            )
        except ValueError as e:
            # Log decryption failure but don't fail entire website load
            logger.error(
                f"Failed to decrypt auth for website {website_record.id}: {str(e)}. "
                "Website will be loaded without auth.",
                extra={
                    "website_id": str(website_record.id),
                    "tenant_id": str(website_record.tenant_id),
                },
            )
            # Set transient flag for crawl task to detect
            # Why: Enables fail-fast behavior in crawler with clear error message
            website_record._auth_decrypt_failed = True  # type: ignore[attr-defined]
            return None

    async def _get_websites(self, space_ids: list[UUID] | UUID) -> list[WebsitesTable]:
        """Fetch websites and decrypt their auth credentials.

        Why: Repository is the encryption boundary. We decrypt here and attach
        the plaintext credentials as a transient attribute on the record object.
        The factory then extracts this and passes it to Website.to_domain().
        """
        # Handle both single UUID and list of UUIDs for backwards compatibility
        if isinstance(space_ids, UUID):
            space_ids = [space_ids]

        ws = WebsitesTable

        stmt = (
            sa.select(ws)
            .where(WEBSITE_SOURCE.visible_to(space_ids))
            .options(selectinload(ws.latest_crawl))  # type: ignore[attr-defined]
            .order_by(ws.created_at)
        )

        website_records = await self.session.execute(stmt)
        websites_db = list(website_records.scalars())

        # Decrypt auth credentials and attach as transient attribute
        for website_record in websites_db:
            website_record._decrypted_http_auth = self._decrypt_website_auth(  # type: ignore[attr-defined]
                website_record
            )

        return websites_db

    async def _load_mcp_server_tools_with_overrides(
        self, space_id: UUID, mcp_servers: list["MCPServer"]
    ) -> list["MCPServer"]:
        """Load the tools of a space's MCP servers, each on or off for the space.

        ``tool_switch`` owns the order of the instance admin's switch and the
        space's. A tool the instance admin switched off is not listed; every
        other tool is, so that the space can switch it.
        """
        if not mcp_servers:
            return mcp_servers

        mcp_server_ids = [server.id for server in mcp_servers]

        # Load all tools for these servers
        tools_query = (
            sa.select(MCPServerToolsTable)
            .where(MCPServerToolsTable.mcp_server_id.in_(mcp_server_ids))
            .order_by(MCPServerToolsTable.name)
        )
        tools_result = await self.session.execute(tools_query)
        tools_db: list[MCPServerToolsTable] = list(tools_result.scalars().all())

        # Load tenant-level tool settings
        tenant_tool_settings_query = sa.select(MCPServerToolSettingsTable).where(
            MCPServerToolSettingsTable.tenant_id == self.tenant_id
        )
        tenant_settings_result = await self.session.execute(tenant_tool_settings_query)
        tenant_settings_db: list[MCPServerToolSettingsTable] = list(
            tenant_settings_result.scalars().all()
        )

        # Create map: tool_id -> is_enabled (tenant level)
        tenant_tool_settings: dict[UUID, bool] = {
            setting.mcp_server_tool_id: setting.is_enabled
            for setting in tenant_settings_db
        }

        # Load space-level tool overrides
        space_overrides_query = sa.select(SpacesMCPServerTools).where(
            SpacesMCPServerTools.space_id == space_id
        )
        space_overrides_result = await self.session.execute(space_overrides_query)
        space_overrides_db = space_overrides_result.scalars().all()

        # Create map: tool_id -> is_enabled (space level)
        space_tool_overrides = {
            override.mcp_server_tool_id: override.is_enabled
            for override in space_overrides_db
        }

        return self._project_space_mcp_server_tools(
            mcp_servers=mcp_servers,
            tools_db=tools_db,
            tenant_tool_settings=tenant_tool_settings,
            space_tool_overrides=space_tool_overrides,
        )

    @staticmethod
    def _project_space_mcp_server_tools(
        *,
        mcp_servers: list["MCPServer"],
        tools_db: Sequence[MCPServerToolsTable],
        tenant_tool_settings: dict[UUID, bool],
        space_tool_overrides: dict[UUID, bool],
    ) -> list["MCPServer"]:
        """The tools a space shows for its servers, each on or off for the space."""
        from collections import defaultdict

        from eneo.mcp_servers.domain.entities.mcp_server import MCPServerTool

        tools_by_server: defaultdict[UUID, list[MCPServerTool]] = defaultdict(list)
        for tool_db in tools_db:
            switch = tool_switch(
                enabled_by_default=tool_db.is_enabled_by_default,
                tenant_setting=tenant_tool_settings.get(tool_db.id),
                space_override=space_tool_overrides.get(tool_db.id),
            )
            # A tool the instance admin switched off is not shown in a space.
            if switch is ToolSwitch.OFF_FOR_ALL:
                continue
            is_enabled = switch is ToolSwitch.ON

            tool = MCPServerTool(
                id=tool_db.id,
                mcp_server_id=tool_db.mcp_server_id,
                name=tool_db.name,
                title=tool_db.title,
                description=tool_db.description,
                input_schema=tool_db.input_schema,
                meta=tool_db.meta,
                ui_resource_sha256=tool_db.ui_resource_sha256,
                is_enabled_by_default=tool_db.is_enabled_by_default,
                enabled_override=is_enabled,
                created_at=tool_db.created_at,
                updated_at=tool_db.updated_at,
            )
            tools_by_server[tool_db.mcp_server_id].append(tool)

        # Attach tools to servers
        for server in mcp_servers:
            server.tools = tools_by_server.get(server.id, [])

        return mcp_servers

    async def _get_apps(self, space_id: UUID) -> Sequence[Apps]:
        stmt = (
            sa.select(Apps)
            .execution_options(populate_existing=True)
            .where(Apps.space_id == space_id)
            .options(
                selectinload(Apps.input_fields),
                selectinload(Apps.attachments).selectinload(AppsFiles.file),
                selectinload(Apps.template).selectinload(AppTemplates.completion_model),
            )
            .order_by(Apps.created_at)
        )
        app_records = await self.session.execute(stmt)
        apps_db = app_records.scalars().all()

        if not apps_db:
            return []

        app_ids = [app.id for app in apps_db]

        # prompt
        stmt = (
            sa.select(Prompts, AppsPrompts.app_id)
            .join(AppsPrompts)
            .where(AppsPrompts.app_id.in_(app_ids))
            .where(AppsPrompts.is_selected)
            .options(selectinload(Prompts.user))
        )
        prompt_records = await self.session.execute(stmt)
        prompts = prompt_records.all()

        for app in apps_db:
            app.prompt = next(  # type: ignore[attr-defined]
                (prompt for prompt, app_id in prompts if app_id == app.id), None
            )

        return apps_db

    def _active_key_assistant_ids(self) -> frozenset[UUID]:
        """The assistant the caller's assistant-scoped key is bound to.

        A scoped load builds it like any named assistant, so the key's role
        rests on the same validated row as with a load of every hidden one: a
        row the factory skips grants no role."""
        key = self.user.active_api_key if self.user is not None else None
        if (
            key is None
            or key.scope_type != ApiKeyScopeType.ASSISTANT
            or key.scope_id is None
        ):
            return frozenset()
        return frozenset({key.scope_id})

    async def _unloaded_hidden_assistant_ids(
        self, space_id: UUID, loaded: AbstractSet[UUID]
    ) -> frozenset[UUID]:
        rows = await self.session.scalars(
            sa.select(Assistants.id)
            .where(Assistants.space_id == space_id)
            .where(Assistants.hidden.is_(True))
            .where(Assistants.is_default.is_(False))
            .where(Assistants.origin != AssistantOrigin.FLOW_MANAGED.value)
            .where(Assistants.id.not_in(loaded))
        )
        return frozenset(rows.all())

    async def assistant_ids(self, space_id: UUID) -> list[UUID]:
        """Every assistant of the space, hidden ones included, which a space
        load does not build: what revoking the space's keys must cover."""
        rows = await self.session.scalars(
            sa.select(Assistants.id)
            .where(Assistants.space_id == space_id)
            .order_by(Assistants.created_at, Assistants.id)
        )
        return list(rows.all())

    async def _linked_transcription_services(
        self, space: Spaces
    ) -> list["TranscriptionServiceConnection"]:
        """A personal space links every connection, like every model; any
        other space only what is granted to it."""
        connections = TranscriptionServiceConnectionRepository(
            self.session, self.tenant_id
        )
        if space.user_id is not None:
            return await connections.list()
        return await connections.list_granted(space.id)

    async def _get_from_query(
        self,
        query: sa.Select[tuple[Spaces]],
        *,
        hidden_assistant_ids: HiddenAssistantSelection = frozenset(),
        with_document_counts: bool = False,
    ) -> Space | None:
        """Load the space with its visible assistants and, of the hidden ones,
        only ``hidden_assistant_ids``: building every hidden assistant of a
        space made each write to one of them cost the whole space."""
        entry_in_db = await self._get_record_with_options(query)
        if not entry_in_db:
            return

        space_ids = effective_space_ids_for(entry_in_db.id, entry_in_db.tenant_space_id)

        collections = await self._get_collections(space_ids)
        websites = await self._get_websites(space_ids)
        integration_knowledge_union = await self._get_integration_knowledge_union(
            space_ids, with_document_counts=with_document_counts
        )

        completion_models = await self.completion_model_repo.all(with_deprecated=True)
        embedding_models = await self.embedding_model_repo.all(with_deprecated=True)
        transcription_models = await self.transcription_model_repo.all(
            with_deprecated=True
        )
        transcription_services = await self._linked_transcription_services(entry_in_db)

        # Get tenant-enabled MCP servers directly
        from sqlalchemy.orm import selectinload as _selectinload

        from eneo.database.tables.security_classifications_table import (
            SecurityClassification as SecurityClassificationDBModel,
        )

        # Capability servers are included even when deactivated: an attached
        # one is a capability marker (resolved to the active provider at ask
        # time), and dropping it here would flip the space's capability toggle
        # off after a provider switch. General servers must be enabled.
        mcp_servers_query = (
            sa.select(MCPServersTable)
            .where(MCPServersTable.tenant_id == self.tenant_id)
            .where(
                sa.or_(
                    MCPServersTable.is_enabled == True,  # noqa: E712
                    MCPServersTable.purpose != GENERAL_PURPOSE,
                )
            )
            .options(
                _selectinload(MCPServersTable.security_classification).selectinload(
                    SecurityClassificationDBModel.tenant
                ),
            )
        )
        mcp_servers_db: Sequence[MCPServersTable] = (
            (await self.session.execute(mcp_servers_query)).scalars().all()
        )

        # Convert to domain entities
        from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
        from eneo.security_classifications.domain.entities.security_classification import (
            SecurityClassification,
        )

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
            for server in mcp_servers_db
        ]

        # Load tools for MCP servers with space-level overrides
        if mcp_servers:
            mcp_servers = await self._load_mcp_server_tools_with_overrides(
                entry_in_db.id, mcp_servers
            )

        if hidden_assistant_ids and hidden_assistant_ids is not HiddenAssistants.ALL:
            hidden_assistant_ids = {
                *hidden_assistant_ids,
                *self._active_key_assistant_ids(),
            }
        assistants = await self._get_assistants(
            space_id=entry_in_db.id,
            hidden_assistant_ids=hidden_assistant_ids,
        )
        unloaded_hidden_assistant_ids = (
            await self._unloaded_hidden_assistant_ids(
                entry_in_db.id, hidden_assistant_ids
            )
            if hidden_assistant_ids and hidden_assistant_ids is not HiddenAssistants.ALL
            else frozenset[UUID]()
        )
        apps = await self._get_apps(space_id=entry_in_db.id)
        (
            assistant_attachments,
            app_attachments,
        ) = await self._load_application_attachments(
            tenant_id=entry_in_db.tenant_id,
            assistants=assistants,
            apps=apps,
        )
        group_chats = await self._get_group_chats(space_id=entry_in_db.id)
        services = await self._get_services(space_id=entry_in_db.id)

        space = self.factory.create_space_from_db(
            entry_in_db,
            user=self.user,
            collections_in_db=collections,
            websites_in_db=websites,
            completion_models=completion_models,
            embedding_models=embedding_models,
            transcription_models=transcription_models,
            transcription_services=transcription_services,
            mcp_servers=mcp_servers,
            assistants_in_db=assistants,
            assistant_attachments=assistant_attachments,
            group_chats_in_db=group_chats,
            apps_in_db=apps,
            app_attachments=app_attachments,
            services_in_db=services,
            integration_knowledge_in_db=integration_knowledge_union,
            security_classification=entry_in_db.security_classification,
            unloaded_hidden_assistant_ids=unloaded_hidden_assistant_ids,
        )
        from eneo.mcp_servers.application.capability_resolver import (
            active_capability_providers,
            availability_from_providers,
        )

        # One provider load serves the tenant-wide and the user-scoped view.
        capability_providers = await active_capability_providers(
            self.session, self.tenant_id
        )
        space.available_capabilities = availability_from_providers(
            capability_providers, space.security_classification
        )
        if space.is_personal():
            space.enabled_capabilities = [
                s.purpose for s in space.available_capabilities if s.available
            ]
        assistants_with_default = [
            *space.assistants,
            *([space.default_assistant] if space.default_assistant else []),
        ]
        if assistants_with_default:
            from eneo.mcp_servers.domain.entities.mcp_server import (
                allowed_capability_purposes,
            )

            # A user-scoped repository narrows availability to the user's
            # groups and permissions; a tenant-only repository (workers) reads
            # the tenant-wide availability.
            personal_availability = availability_from_providers(
                capability_providers,
                space.security_classification,
                user_group_ids=(
                    self.user.user_groups_ids if self.user is not None else None
                ),
                allowed_purposes=(
                    allowed_capability_purposes(self.user.permissions)
                    if self.user is not None
                    else None
                ),
            )
            for assistant in assistants_with_default:
                assistant.available_capabilities = [
                    state
                    if space.is_personal()
                    or state.purpose in space.enabled_capabilities
                    else state.model_copy(
                        update={"available": False, "reason": "space_disabled"}
                    )
                    for state in personal_availability
                ]
        return space

    async def _get_record_with_options(
        self,
        query: sa.Select[tuple[Spaces]]
        | ReturningInsert[tuple[Spaces]]
        | ReturningUpdate[tuple[Spaces]],
    ) -> Spaces | None:
        for option in self._options():
            query = query.options(option)

        return await self.session.scalar(
            query.execution_options(populate_existing=True)
        )

    async def _get_records_with_options(
        self, query: sa.Select[tuple[Spaces]]
    ) -> Sequence[Spaces]:
        for option in self._options():
            query = query.options(option)

        result = await self.session.scalars(
            query.execution_options(populate_existing=True)
        )
        return result.all()

    async def add(self, space: Space) -> Space:
        query = (
            sa.insert(Spaces)
            .values(
                name=space.name,
                description=space.description,
                tenant_id=space.tenant_id,
                user_id=space.user_id,
                tenant_space_id=space.tenant_space_id,
            )
            .returning(Spaces)
        )

        try:
            entry_in_db = await self._get_record_with_options(query)
        except IntegrityError as e:
            raise UniqueException("Users can only have one personal space") from e

        assert entry_in_db is not None
        # Creation seeds only Space-owned settings. Child resources have their
        # own create operations, so even initialization cannot reconcile them.
        # A new space stores no links yet, so the edits are shown none.
        await self.update_settings(
            entry_in_db.id,
            SpaceUpdate(
                completion_models=LinkEdit(
                    tuple(m.id for m in space.completion_models), frozenset()
                ),
                embedding_models=LinkEdit(
                    tuple(m.id for m in space.embedding_models), frozenset()
                ),
                transcription_models=LinkEdit(
                    tuple(m.id for m in space.transcription_models), frozenset()
                ),
                mcp_servers=LinkEdit(
                    tuple(server.id for server in space.mcp_servers), frozenset()
                ),
                enabled_capabilities=space.enabled_capabilities,
            ),
        )
        for member in space.members.values():
            await self.add_member(entry_in_db.id, member)
        for group_member in space.group_members.values():
            await self.add_group_member(entry_in_db.id, group_member)
        return await self.one(id=entry_in_db.id)

    def _in_caller_tenant(
        self, query: sa.Select[tuple[Spaces]]
    ) -> sa.Select[tuple[Spaces]]:
        """Restrict a request-facing space lookup to the caller's tenant.

        Every lookup that addresses a space by an id taken from the request
        (directly, or through one of its resources) goes through here, so a
        foreign-tenant id resolves to "not found" rather than to a space the
        actor then has to reject. Lookups that address a tenant explicitly,
        such as ``get_space_by_name_and_tenant``, stay privileged.
        """
        return query.where(Spaces.tenant_id == self.tenant_id)

    async def one_or_none(
        self, id: UUID, *, hidden_assistant_ids: AbstractSet[UUID] = frozenset()
    ) -> Optional[Space]:
        query = self._in_caller_tenant(sa.select(Spaces).where(Spaces.id == id))

        return await self._get_from_query(
            query,
            hidden_assistant_ids=hidden_assistant_ids,
            with_document_counts=True,
        )

    async def one(
        self, id: UUID, *, hidden_assistant_ids: AbstractSet[UUID] = frozenset()
    ) -> Space:
        space = await self.one_or_none(id=id, hidden_assistant_ids=hidden_assistant_ids)

        if space is None:
            raise NotFoundException()

        return space

    async def get_applications_projection(
        self, id: UUID
    ) -> SpaceApplicationsProjection:
        space_in_db = await self.session.scalar(
            self._in_caller_tenant(sa.select(Spaces).where(Spaces.id == id))
        )
        if space_in_db is None:
            raise NotFoundException()

        member_roles = dict(
            (
                await self.session.execute(
                    sa.select(SpacesUsers.user_id, SpacesUsers.role)
                    .join(Users, Users.id == SpacesUsers.user_id)
                    .where(SpacesUsers.space_id == id)
                    .where(Users.deleted_at.is_(None))
                )
            )
            .tuples()
            .all()
        )
        group_member_roles = dict(
            (
                await self.session.execute(
                    sa.select(
                        SpacesUserGroups.user_group_id,
                        SpacesUserGroups.role,
                    )
                    .join(
                        UserGroups,
                        UserGroups.id == SpacesUserGroups.user_group_id,
                    )
                    .where(SpacesUserGroups.space_id == id)
                    .where(
                        sa.or_(
                            UserGroups.state.is_(None),
                            UserGroups.state != UserGroupState.DELETED.value,
                        )
                    )
                )
            )
            .tuples()
            .all()
        )
        assistants = (
            await self.session.scalars(
                sa.select(Assistants)
                .execution_options(populate_existing=True)
                .where(Assistants.space_id == id)
                .order_by(Assistants.created_at)
            )
        ).all()
        group_chats = (
            await self.session.scalars(
                sa.select(GroupChatsTable).where(GroupChatsTable.space_id == id)
            )
        ).all()
        apps = (
            await self.session.scalars(
                sa.select(Apps).where(Apps.space_id == id).order_by(Apps.created_at)
            )
        ).all()
        services = (
            await self.session.scalars(
                sa.select(Services).where(Services.space_id == id)
            )
        ).all()
        completion_models = await self.completion_model_repo.all(with_deprecated=True)

        return self.factory.create_applications_projection(
            space_in_db=space_in_db,
            member_roles=member_roles,
            group_member_roles=group_member_roles,
            assistants_in_db=assistants,
            group_chats_in_db=group_chats,
            apps_in_db=apps,
            services_in_db=services,
            completion_models=completion_models,
        )

    async def delete(self, id: UUID):
        query = sa.delete(Spaces).where(Spaces.id == id)
        await self.session.execute(query)

    async def has_flow_delete_blockers(self, space_id: UUID) -> bool:
        return await space_has_flow_delete_blockers(self.session, space_id)

    async def has_active_legal_hold(self, space_id: UUID) -> bool:
        return await space_has_active_legal_hold(self.session, space_id)

    async def query(self, **filters: object) -> None:
        raise NotImplementedError()

    async def get_spaces_for_member(
        self, include_applications: bool = False
    ) -> list[Space]:
        user = self._require_user()
        user_id = user.id
        user_group_ids = list(user.user_groups_ids) if user.user_groups_ids else []

        direct_member_query = (
            sa.select(Spaces.id)
            .join(SpacesUsers, Spaces.members)
            .where(SpacesUsers.user_id == user_id)
        )

        # Query for group membership (if user belongs to any groups)
        if user_group_ids:
            group_member_query = (
                sa.select(Spaces.id)
                .join(SpacesUserGroups, Spaces.group_members)
                .where(SpacesUserGroups.user_group_id.in_(user_group_ids))
            )
            # Union of both membership types
            combined_query = sa.union(
                direct_member_query, group_member_query
            ).subquery()
        else:
            combined_query = direct_member_query.subquery()

        query = (
            sa.select(Spaces)
            .where(Spaces.id.in_(sa.select(combined_query.c.id)))
            .distinct()
            .order_by(Spaces.created_at)
        )

        records = await self._get_records_with_options(query)

        spaces: list[Space] = []
        for record in records:
            if include_applications:
                assistants = await self._get_assistants(space_id=record.id)
                apps = await self._get_apps(space_id=record.id)
                (
                    assistant_attachments,
                    app_attachments,
                ) = await self._load_application_attachments(
                    tenant_id=record.tenant_id,
                    assistants=assistants,
                    apps=apps,
                )
                group_chats = await self._get_group_chats(space_id=record.id)
            else:
                assistants: Sequence[Assistants] = []
                apps: Sequence[Apps] = []
                assistant_attachments: dict[UUID, list[File]] = {}
                app_attachments: dict[UUID, list[File]] = {}
                group_chats: Sequence[GroupChatsTable] = []

            spaces.append(
                self.factory.create_space_from_db(
                    record,
                    user=user,
                    assistants_in_db=assistants,
                    assistant_attachments=assistant_attachments,
                    apps_in_db=apps,
                    app_attachments=app_attachments,
                    group_chats_in_db=group_chats,
                )
            )

        return spaces

    async def get_personal_space(self, user_id: UUID) -> Space | None:
        query = self._in_caller_tenant(
            sa.select(Spaces).where(Spaces.user_id == user_id)
        )

        return await self._get_from_query(query, with_document_counts=True)

    async def get_space_by_assistant(
        self,
        assistant_id: UUID,
        *,
        hidden_assistant_ids: AbstractSet[UUID] = frozenset(),
    ) -> Space:
        """The space of ``assistant_id`` with that assistant built, hidden or
        not, plus the hidden ``hidden_assistant_ids``. The default assistant's
        tools are every other assistant of its space, so loading by it builds
        every hidden one."""
        query = self._in_caller_tenant(
            sa.select(Spaces).join(Assistants).where(Assistants.id == assistant_id)
        )
        is_default = await self.session.scalar(
            sa.select(Assistants.is_default).where(Assistants.id == assistant_id)
        )

        space = await self._get_from_query(
            query,
            hidden_assistant_ids=(
                HiddenAssistants.ALL
                if is_default
                else {assistant_id, *hidden_assistant_ids}
            ),
        )

        if space is None:
            raise NotFoundException()

        return space

    async def get_space_by_app(self, app_id: UUID) -> Space:
        query = self._in_caller_tenant(
            sa.select(Spaces).join(Apps).where(Apps.id == app_id)
        )

        space = await self._get_from_query(query)

        if space is None:
            raise NotFoundException()

        return space

    async def get_space_by_service(self, service_id: UUID) -> Space:
        query = self._in_caller_tenant(
            sa.select(Spaces).join(Services).where(Services.id == service_id)
        )

        space = await self._get_from_query(query)

        if space is None:
            raise NotFoundException()

        return space

    async def get_space_by_group_chat(self, group_chat_id: UUID) -> Space:
        query = self._in_caller_tenant(
            sa.select(Spaces)
            .join(GroupChatsTable)
            .where(GroupChatsTable.id == group_chat_id)
        )
        space = await self._get_from_query(query=query)

        if space is None:
            raise NotFoundException()

        return space

    async def get_execution_space(self, space_id: UUID) -> Space:
        """Read classification context without hydrating application content."""
        return await self._classification_context(space_id)

    async def get_transcription_space(self, space_id: UUID) -> Space:
        """``get_execution_space`` with the transcription services the space
        links, as a full load links them: the space decides which of them it
        may use by the rules of a full load, without its applications or any
        other link being read."""
        return await self._classification_context(
            space_id, with_transcription_services=True
        )

    async def _classification_context(
        self, space_id: UUID, *, with_transcription_services: bool = False
    ) -> Space:
        record = await self.session.scalar(
            sa.select(Spaces)
            .where(Spaces.id == space_id, Spaces.tenant_id == self.tenant_id)
            .options(
                raiseload("*"),
                selectinload(Spaces.security_classification).selectinload(
                    SecurityClassificationDBModel.tenant
                ),
            )
        )
        if record is None:
            raise NotFoundException()
        return Space(
            id=record.id,
            tenant_id=record.tenant_id,
            tenant_space_id=record.tenant_space_id,
            user_id=record.user_id,
            name=record.name,
            description=record.description,
            embedding_models=[],
            completion_models=[],
            transcription_models=[],
            mcp_servers=[],
            default_assistant=None,
            assistants=[],
            apps=[],
            services=[],
            websites=[],
            collections=[],
            integration_knowledge_list=[],
            members={},
            security_classification=SecurityClassification.to_domain(
                record.security_classification
            ),
            transcription_services=(
                await self._linked_transcription_services(record)
                if with_transcription_services
                else None
            ),
        )

    async def get_execution_assistant(
        self, *, space_id: UUID, assistant_id: UUID
    ) -> Assistant | None:
        """Read live metadata and MCP configuration without mutable selections."""
        record = await self.session.scalar(
            sa.select(Assistants)
            .join(Spaces, Spaces.id == Assistants.space_id)
            .where(
                Assistants.id == assistant_id,
                Spaces.id == space_id,
                Spaces.tenant_id == self.tenant_id,
            )
            .options(
                raiseload("*"),
                selectinload(Assistants.mcp_servers),
            )
        )
        if record is None:
            return None
        prompt = await self.session.scalar(
            sa.select(Prompts)
            .join(PromptsAssistants)
            .where(
                PromptsAssistants.assistant_id == assistant_id,
                PromptsAssistants.is_selected,
                Prompts.tenant_id == self.tenant_id,
            )
            .options(selectinload(Prompts.user))
        )
        mcp_servers = MCPServerMapper.to_entities(record.mcp_servers)
        return Assistant(
            id=record.id,
            space_id=space_id,
            user=UserSparse.model_validate(self.user)
            if self.user is not None
            else None,
            name=record.name,
            prompt=PromptFactory.create_prompt_from_db(prompt, is_selected=True)
            if prompt
            else None,
            completion_model=None,
            completion_model_kwargs=ModelKwargs(),
            logging_enabled=record.logging_enabled,
            websites=[],
            collections=[],
            attachments=[],
            published=record.published,
            mcp_servers=[
                server for server in mcp_servers if server.purpose == GENERAL_PURPOSE
            ],
        )

    async def get_collection(self, collection_id: UUID) -> Collection:
        record = await self.session.scalar(
            sa.select(CollectionsTable).where(
                CollectionsTable.id == collection_id,
                CollectionsTable.tenant_id == self.tenant_id,
            )
        )
        if record is None or record.embedding_model_id is None:
            raise NotFoundException()
        embedding_model = await self.embedding_model_repo.one(record.embedding_model_id)
        count = await self.session.scalar(
            sa.select(sa.func.count(InfoBlobs.id)).where(
                InfoBlobs.group_id == record.id, active_info_blob_version()
            )
        )
        return Collection.to_domain(
            record, embedding_model=embedding_model, num_info_blobs=count or 0
        )

    async def get_website(self, website_id: UUID) -> Website:
        mapper = sa.inspect(WebsitesTable)
        assert mapper is not None
        record = await self.session.scalar(
            sa.select(WebsitesTable)
            .where(
                WebsitesTable.id == website_id,
                WebsitesTable.tenant_id == self.tenant_id,
            )
            .options(selectinload(mapper.relationships["latest_crawl"].class_attribute))
        )
        if record is None:
            raise NotFoundException()
        embedding_model = await self.embedding_model_repo.one(record.embedding_model_id)
        return Website.to_domain(
            record,
            embedding_model=embedding_model,
            http_auth=self._decrypt_website_auth(record),
        )

    async def get_integration_knowledge(
        self, resource_id: UUID
    ) -> IntegrationKnowledgeEntity:
        record = await self.session.scalar(
            sa.select(IntegrationKnowledge)
            .where(
                IntegrationKnowledge.id == resource_id,
                IntegrationKnowledge.tenant_id == self.tenant_id,
            )
            .options(
                selectinload(IntegrationKnowledge.user_integration)
                .selectinload(UserIntegrationDBModel.tenant_integration)
                .selectinload(TenantIntegrationDBModel.integration),
                selectinload(IntegrationKnowledge.sharepoint_subscription),
            )
        )
        if record is None:
            raise NotFoundException()
        embedding_model = await self.embedding_model_repo.one(record.embedding_model_id)
        return IntegrationKnowledgeFactory.create_entity(record, embedding_model)

    async def get_info_blob_read_access(
        self, info_blob: "InfoBlobInDB"
    ) -> list[SpaceAccessFacts]:
        """Reader memberships through the source's ownership and distribution.

        The inverse of what ``_get_from_query`` loads: a user may read a blob
        from any space they belong to that sees the blob's source, including
        child spaces of an organization the source is visible to. These facts
        cover membership-derived reads only; resource-scoped key IDs are omitted.
        """
        user = self._require_user()
        if info_blob.tenant_id != user.tenant_id:
            return []
        source, source_id = knowledge_source_for(info_blob)
        return await self.get_knowledge_source_read_access(source, source_id)

    async def get_knowledge_source_read_access(
        self, source: KnowledgeSource, source_id: UUID
    ) -> list[SpaceAccessFacts]:
        """Reader memberships for a source in this tenant, including distribution."""
        user = self._require_user()
        source_space_ids = source.spaces_seeing(source_id, user.tenant_id)
        return await self._member_access_facts(
            # Inverse of effective_space_ids_for: the space itself, or a
            # child space whose organization space sees the source.
            sa.or_(
                Spaces.id.in_(source_space_ids),
                Spaces.tenant_space_id.in_(source_space_ids),
            )
        )

    async def get_member_access_facts(self) -> list[SpaceAccessFacts]:
        """Access facts for every space the user belongs to: their personal
        space, each space they are a member of directly or through a group,
        and the organization space while they hold the admin permission.
        Reads membership columns only; no space is hydrated."""
        return await self._member_access_facts()

    async def _member_access_facts(
        self, *space_filters: sa.ColumnElement[bool]
    ) -> list[SpaceAccessFacts]:
        user = self._require_user()
        user_group_ids = sa.select(UserGroups.id).where(
            UserGroups.id.in_(user.user_groups_ids),
            UserGroups.tenant_id == user.tenant_id,
            sa.or_(
                UserGroups.state.is_(None),
                UserGroups.state != UserGroupState.DELETED.value,
            ),
        )
        group_membership = SpacesUserGroups.user_group_id.in_(user_group_ids)
        query = (
            sa.select(
                Spaces.id,
                Spaces.tenant_id,
                Spaces.user_id,
                Spaces.tenant_space_id,
                sa.Nullable(SpacesUsers.role),
            )
            .outerjoin(
                SpacesUsers,
                sa.and_(
                    SpacesUsers.space_id == Spaces.id,
                    SpacesUsers.user_id == user.id,
                ),
            )
            .where(
                Spaces.tenant_id == user.tenant_id,
                *space_filters,
                sa.or_(
                    Spaces.user_id == user.id,
                    SpacesUsers.user_id.is_not(None),
                    Spaces.group_members.any(group_membership),
                    # Its role follows the admin permission, not a row.
                    sa.and_(
                        Spaces.user_id.is_(None),
                        Spaces.tenant_space_id.is_(None),
                        sa.true()
                        if organization_space_role(user) is not None
                        else sa.false(),
                    ),
                ),
            )
        )
        spaces = (await self.session.execute(query)).tuples().all()
        if not spaces:
            return []

        group_roles: dict[UUID, dict[UUID, SpaceRoleFact]] = {}
        if user.user_groups_ids:
            rows = await self.session.execute(
                sa.select(
                    SpacesUserGroups.space_id,
                    SpacesUserGroups.user_group_id,
                    SpacesUserGroups.role,
                ).where(
                    SpacesUserGroups.space_id.in_(
                        [space_id for space_id, _, _, _, _ in spaces]
                    ),
                    group_membership,
                )
            )
            for space_id, group_id, role in rows.tuples():
                group_roles.setdefault(space_id, {})[group_id] = SpaceRoleFact(
                    id=group_id, role=role
                )

        return [
            SpaceAccessFacts(
                id=space_id,
                tenant_id=tenant_id,
                user_id=user_id,
                tenant_space_id=tenant_space_id,
                members=(
                    {user.id: SpaceRoleFact(id=user.id, role=role)}
                    if role is not None
                    else {}
                ),
                group_members=group_roles.get(space_id, {}),
                default_assistant_id=None,
                assistant_ids=frozenset(),
                app_ids=frozenset(),
            )
            for space_id, tenant_id, user_id, tenant_space_id, role in spaces
        ]

    async def get_knowledge_source_owner_access(
        self, source: KnowledgeSource, source_id: UUID
    ) -> SpaceAccessFacts | None:
        """The owning space of a source in this tenant, without membership facts.

        For service API keys, which have no memberships and authorize through
        their scope and permission in ``SpaceActor``.
        """
        query = (
            sa.select(
                Spaces.id, Spaces.tenant_id, Spaces.user_id, Spaces.tenant_space_id
            )
            .join(source.table, source.table.space_id == Spaces.id)
            .where(
                source.table.id == source_id,
                source.table.tenant_id == self.tenant_id,
                Spaces.tenant_id == self.tenant_id,
            )
        )
        space = (await self.session.execute(query)).tuples().one_or_none()
        if space is None:
            return None
        space_id, tenant_id, user_id, tenant_space_id = space
        return SpaceAccessFacts(
            id=space_id,
            tenant_id=tenant_id,
            user_id=user_id,
            tenant_space_id=tenant_space_id,
            members={},
            group_members={},
            default_assistant_id=None,
            assistant_ids=frozenset(),
            app_ids=frozenset(),
        )

    async def get_space_by_collection(self, collection_id: UUID) -> Space:
        query = self._in_caller_tenant(
            sa.select(Spaces)
            .join(CollectionsTable)
            .where(CollectionsTable.id == collection_id)
        )

        space = await self._get_from_query(query)

        if space is None:
            raise NotFoundException()

        return space

    async def get_website_access_facts(self, website_id: UUID) -> SpaceAccessFacts:
        """Load only this caller's facts for website access, not the space aggregate."""
        user = self._require_user()
        space = (
            (
                await self.session.execute(
                    _select_space_rows()
                    .join(WebsitesTable, WebsitesTable.space_id == Spaces.id)
                    .where(WebsitesTable.id == website_id)
                    .where(WebsitesTable.tenant_id == user.tenant_id)
                    .where(Spaces.tenant_id == user.tenant_id)
                )
            )
            .tuples()
            .one_or_none()
        )
        if space is None:
            raise NotFoundException("Website not found")
        return await self._caller_access_facts(user, space)

    async def get_space_access_facts(self, space_id: UUID) -> SpaceAccessFacts:
        """This caller's facts for a space of their tenant, not the space aggregate.

        Only the caller's own membership, their groups' memberships and the
        assistant or app their key is scoped to are filled in. Other members,
        other assistants and apps, and the default assistant are left out, so
        the facts serve this caller's checks only: never member management or
        checks on the default assistant, which need the space itself.
        """
        facts = await self.get_spaces_access_facts([space_id])
        if space_id not in facts:
            raise NotFoundException()
        return facts[space_id]

    async def get_spaces_access_facts(
        self, space_ids: Sequence[UUID]
    ) -> dict[UUID, SpaceAccessFacts]:
        """This caller's facts for each space; other tenants' spaces are left out.

        As ``get_space_access_facts``: only the caller's own membership and key
        scope, never other members or the default assistant.
        """
        if not space_ids:
            return {}
        user = self._require_user()
        spaces = (
            (
                await self.session.execute(
                    _select_space_rows().where(
                        Spaces.id.in_(space_ids),
                        Spaces.tenant_id == user.tenant_id,
                    )
                )
            )
            .tuples()
            .all()
        )
        return {
            space[0]: await self._caller_access_facts(user, space) for space in spaces
        }

    async def _caller_access_facts(
        self, user: "UserInDB", space: _SpaceRow
    ) -> SpaceAccessFacts:
        space_id, tenant_id, owner_user_id, tenant_space_id = space
        return await _caller_space_access_facts(
            self.session,
            user=user,
            space_id=space_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            tenant_space_id=tenant_space_id,
            include_hidden_assistants=True,
            caller_group_ids=user.user_groups_ids,
        )

    async def get_space_by_website(self, website_id: UUID) -> Space:
        query = self._in_caller_tenant(
            sa.select(Spaces).join(WebsitesTable).where(WebsitesTable.id == website_id)
        )

        space = await self._get_from_query(query)

        if space is None:
            raise NotFoundException()

        return space

    async def get_space_by_integration_knowledge(
        self, integration_knowledge_id: UUID
    ) -> Space:
        query = self._in_caller_tenant(
            sa.select(Spaces)
            .join(IntegrationKnowledge)
            .where(IntegrationKnowledge.id == integration_knowledge_id)
        )

        space = await self._get_from_query(query)

        if space is None:
            raise NotFoundException()

        return space

    async def get_space_by_session(self, session_id: UUID) -> Space | None:
        session_stmt = sa.select(Sessions).where(Sessions.id == session_id)
        session = await self.session.scalar(session_stmt)

        if session is None:
            raise NotFoundException(f"Session with ID {session_id} not found")

        # find space through assistant
        if session.assistant_id is not None:
            return await self.get_space_by_assistant(assistant_id=session.assistant_id)

        # find space through group chat
        if session.group_chat_id is not None:
            return await self.get_space_by_group_chat(
                group_chat_id=session.group_chat_id
            )

    async def _get_integration_knowledge_union(
        self, space_ids: list[UUID], *, with_document_counts: bool = False
    ) -> list[IntegrationKnowledge]:
        """Integration knowledge owned by the spaces or distributed to them.

        ``document_count`` is a COUNT over info_blobs per item, so it is only
        attached for lookups whose knowledge list is served to the UI (``one``,
        ``one_or_none``, ``get_personal_space``, ``get_space_by_name_and_tenant``
        for the organization space). Assistant, app, session and other
        resource lookups on the chat path leave it unset.
        """
        ik = IntegrationKnowledge

        stmt = (
            sa.select(ik)
            .where(INTEGRATION_KNOWLEDGE_SOURCE.visible_to(space_ids))
            .options(
                selectinload(ik.embedding_model),
                selectinload(ik.user_integration)
                .selectinload(UserIntegrationDBModel.tenant_integration)
                .selectinload(TenantIntegrationDBModel.integration),
                selectinload(ik.sharepoint_subscription),
            )
            .order_by(ik.created_at)
        )
        rows = await self.session.execute(stmt)
        records = list(rows.scalars().all())
        if with_document_counts:
            counts = await active_document_counts(
                self.session, [record.id for record in records]
            )
            for record in records:
                setattr(record, "document_count", counts.get(record.id, 0))
        return records

    async def get_visible_website_ids(
        self, space_id: UUID, tenant_space_id: UUID | None
    ) -> list[UUID]:
        """Ids of the websites a space shows, as the space aggregate selects them."""
        user = self._require_user()
        ids = await self.session.scalars(
            sa.select(WebsitesTable.id)
            .where(
                WEBSITE_SOURCE.visible_to(
                    effective_space_ids_for(space_id, tenant_space_id)
                ),
                WebsitesTable.tenant_id == user.tenant_id,
            )
            .order_by(WebsitesTable.created_at)
        )
        return list(ids.all())

    async def get_visible_integration_knowledge_ids(
        self, space_id: UUID, tenant_space_id: UUID | None
    ) -> list[UUID]:
        """Ids of the integration knowledge a space shows, as the loader sees it."""
        user = self._require_user()
        ik = IntegrationKnowledge
        ids = await self.session.scalars(
            sa.select(ik.id)
            .where(
                INTEGRATION_KNOWLEDGE_SOURCE.visible_to(
                    effective_space_ids_for(space_id, tenant_space_id)
                ),
                ik.tenant_id == user.tenant_id,
            )
            .order_by(ik.created_at)
        )
        return list(ids.all())

    async def get_space_by_name_and_tenant(
        self, name: str, tenant_id: UUID
    ) -> Space | None:
        q = sa.select(Spaces).where(
            Spaces.name == name,
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
        return await self._get_from_query(q, with_document_counts=True)

    async def create_org_space_for_tenant(
        self, name: str, description: str, tenant_id: UUID
    ) -> Space:
        """Create organization space for a tenant. Called when tenant is created."""
        space = self.factory.create_space(
            name=name,
            tenant_id=tenant_id,
            user_id=None,
            tenant_space_id=None,
            description=description,
        )
        # Use repo.add to ensure all relationships are properly set up
        return await self.add(space)


async def read_space_access_facts(
    session: AsyncSession, *, user: "UserInDB", space_id: UUID
) -> SpaceAccessFacts | None:
    """This caller's access facts for one space of their tenant, or None.

    Reads plain rows, never the Space entity: a session that already holds the
    space (members loaded) would otherwise answer from what it loaded before.
    A key scoped to a hidden assistant is not a key of the space's
    assistants, exactly as ``Space.assistants`` decides for ``SpaceActor``,
    and one scoped to a flow-managed assistant never is. Group roles count only through the caller's current
    memberships, not the group list loaded with the principal, so a removed
    membership is not a role.
    """
    space = (
        await session.execute(
            sa.select(Spaces.tenant_id, Spaces.user_id, Spaces.tenant_space_id).where(
                Spaces.id == space_id, Spaces.tenant_id == user.tenant_id
            )
        )
    ).one_or_none()
    if space is None:
        return None
    tenant_id, owner_user_id, tenant_space_id = space
    return await _caller_space_access_facts(
        session,
        user=user,
        space_id=space_id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        tenant_space_id=tenant_space_id,
        include_hidden_assistants=False,
        caller_group_ids=sa.select(usergroups_users_table.c.user_group_id).where(
            usergroups_users_table.c.user_id == user.id
        ),
    )


async def _caller_space_access_facts(
    session: AsyncSession,
    *,
    user: "UserInDB",
    space_id: UUID,
    tenant_id: UUID,
    owner_user_id: UUID | None,
    tenant_space_id: UUID | None,
    include_hidden_assistants: bool,
    caller_group_ids: "AbstractSet[UUID] | sa.Select[tuple[UUID]]",
) -> SpaceAccessFacts:
    """The caller's direct and group roles in the space, and the scoped API
    key's resource in it: everything ``SpaceActor`` needs to decide."""
    member_rows = await session.execute(
        sa.select(SpacesUsers.user_id, SpacesUsers.role)
        .join(Users, Users.id == SpacesUsers.user_id)
        .where(
            SpacesUsers.space_id == space_id,
            SpacesUsers.user_id == user.id,
            Users.deleted_at.is_(None),
        )
    )
    group_rows = await session.execute(
        sa.select(SpacesUserGroups.user_group_id, SpacesUserGroups.role)
        .join(UserGroups, UserGroups.id == SpacesUserGroups.user_group_id)
        .where(SpacesUserGroups.space_id == space_id)
        .where(SpacesUserGroups.user_group_id.in_(caller_group_ids))
        .where(UserGroups.tenant_id == user.tenant_id)
        .where(
            sa.or_(
                UserGroups.state.is_(None),
                UserGroups.state != UserGroupState.DELETED.value,
            )
        )
    )
    assistant_ids: Sequence[UUID] = ()
    app_ids: Sequence[UUID] = ()
    key = user.active_api_key
    if key is not None and key.scope_type == ApiKeyScopeType.ASSISTANT:
        assistant_query = sa.select(Assistants.id).where(
            Assistants.space_id == space_id,
            Assistants.id == key.scope_id,
            Assistants.is_default.is_(False),
            Assistants.origin != AssistantOrigin.FLOW_MANAGED.value,
        )
        if not include_hidden_assistants:
            assistant_query = assistant_query.where(Assistants.hidden.is_(False))
        assistant_ids = (await session.scalars(assistant_query)).all()
    elif key is not None and key.scope_type == ApiKeyScopeType.APP:
        app_ids = (
            await session.scalars(
                sa.select(Apps.id).where(
                    Apps.space_id == space_id, Apps.id == key.scope_id
                )
            )
        ).all()
    return SpaceAccessFacts(
        id=space_id,
        tenant_id=tenant_id,
        user_id=owner_user_id,
        tenant_space_id=tenant_space_id,
        members={id: SpaceRoleFact(id=id, role=role) for id, role in member_rows},
        group_members={id: SpaceRoleFact(id=id, role=role) for id, role in group_rows},
        # No caller of these facts authorizes as the default assistant.
        default_assistant_id=None,
        assistant_ids=frozenset(assistant_ids),
        app_ids=frozenset(app_ids),
    )
