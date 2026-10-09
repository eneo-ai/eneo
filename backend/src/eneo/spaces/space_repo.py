from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.dml import ReturningInsert, ReturningUpdate

from eneo.actors.actors.space_actor import SpaceAccessFacts, SpaceRoleFact
from eneo.authentication.auth_models import ApiKeyScopeType
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
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import Users
from eneo.database.tables.websites_spaces_table import WebsitesSpaces
from eneo.database.tables.websites_table import Websites as WebsitesTable
from eneo.files.file_content_loader import FileAttachmentGroup, FileContentLoader
from eneo.files.file_models import File, FileMetadata
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UniqueException,
)
from eneo.main.logging import get_logger
from eneo.mcp_servers.domain.entities.mcp_server import GENERAL_PURPOSE
from eneo.spaces.api.space_models import SpaceGroupMember, SpaceMember, SpaceRoleValue
from eneo.spaces.space import Space
from eneo.spaces.space_applications_projection import SpaceApplicationsProjection
from eneo.spaces.space_factory import SpaceFactory
from eneo.spaces.space_update import SpaceUpdate
from eneo.spaces.utils.space_utils import effective_space_ids_for
from eneo.user_groups.user_group import UserGroupState

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
    from eneo.transcription_models.domain.transcription_model_repo import (
        TranscriptionModelRepository,
    )
    from eneo.users.user import UserInDB
    from eneo.websites.domain.http_auth_credentials import HttpAuthCredentials
    from eneo.websites.infrastructure.http_auth_encryption import (
        HttpAuthEncryptionService,
    )


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
        session: AsyncSession,
        user: "UserInDB",
        factory: SpaceFactory,
        file_content_loader: FileContentLoader,
        completion_model_repo: "CompletionModelRepository",
        transcription_model_repo: "TranscriptionModelRepository",
        embedding_model_repo: "EmbeddingModelRepository",
        http_auth_encryption: "HttpAuthEncryptionService",
    ):
        super().__init__()
        self.session = session
        self.user = user
        self.factory = factory
        self.file_content_loader = file_content_loader
        self.completion_model_repo = completion_model_repo
        self.transcription_model_repo = transcription_model_repo
        self.embedding_model_repo = embedding_model_repo
        self.http_auth_encryption = http_auth_encryption

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
            .where(Spaces.id == space_id, Spaces.tenant_id == self.user.tenant_id)
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
        if change.completion_model_ids is not None:
            await replace_association_ids(
                self.session,
                SpacesCompletionModels,
                SpacesCompletionModels.space_id,
                space_id,
                SpacesCompletionModels.completion_model_id,
                change.completion_model_ids,
            )
        if change.embedding_model_ids is not None:
            await replace_association_ids(
                self.session,
                SpacesEmbeddingModels,
                SpacesEmbeddingModels.space_id,
                space_id,
                SpacesEmbeddingModels.embedding_model_id,
                change.embedding_model_ids,
            )
        if change.transcription_model_ids is not None:
            await replace_association_ids(
                self.session,
                SpacesTranscriptionModels,
                SpacesTranscriptionModels.space_id,
                space_id,
                SpacesTranscriptionModels.transcription_model_id,
                change.transcription_model_ids,
            )
        if change.mcp_server_ids is not None:
            await replace_association_ids(
                self.session,
                SpacesMCPServers,
                SpacesMCPServers.space_id,
                space_id,
                SpacesMCPServers.mcp_server_id,
                change.mcp_server_ids,
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
                SecurityClassificationDBModel.tenant_id == self.user.tenant_id,
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
            selected_servers = sa.select(SpacesMCPServers.mcp_server_id).where(
                SpacesMCPServers.space_id == space_id
            )
            valid = set(
                await self.session.scalars(
                    sa.select(MCPServerToolsTable.id).where(
                        MCPServerToolsTable.mcp_server_id.in_(selected_servers),
                        MCPServerToolsTable.id.in_(
                            [key for key, _ in change.mcp_tools]
                        ),
                    )
                )
            )
            if {key for key, _ in change.mcp_tools} - valid:
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
                dict(change.mcp_tools),
            )

    async def _load_assistant_mcp_server_tools_with_overrides(
        self,
        space_id: UUID,
        assistant_id: UUID,
        mcp_servers: list["MCPServer"],
        assistant_tool_overrides: dict[UUID, bool] | None = None,
    ) -> list["MCPServer"]:
        """Load tools for assistant's MCP servers and apply space + assistant-level overrides.

        Hierarchy:
        1. Tool default (is_enabled_by_default)
        2. Tenant override (mcp_server_tool_settings.is_enabled) - if exists
        3. Space override (spaces_mcp_server_tools.is_enabled) - if exists
        4. Assistant override (assistant_mcp_server_tools.is_enabled) - if exists

        Rules:
        - If tenant disables a tool, it won't appear at all (filtered out)
        - If space disables a tool, it won't appear in assistant (filtered out)
        - Assistant can only override tools that are space-enabled
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
            MCPServerToolSettingsTable.tenant_id == self.user.tenant_id
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
            # Determine effective is_enabled status
            # Priority: assistant override > space override > tenant override > tool default
            tenant_enabled = tenant_tool_settings.get(
                tool_db.id, tool_db.is_enabled_by_default
            )

            # If tenant disabled this tool, skip it entirely (don't show in space/assistant)
            if (
                tool_db.id in tenant_tool_settings
                and not tenant_tool_settings[tool_db.id]
            ):
                continue

            # Apply space override if exists, otherwise use tenant/default
            if tool_db.id in space_tool_overrides:
                space_enabled = space_tool_overrides[tool_db.id]
            else:
                space_enabled = tenant_enabled

            # If space disabled this tool, skip it (don't show in assistant)
            if not space_enabled:
                continue

            # Apply assistant override if exists, otherwise default to OFF for assistants
            # (tools must be explicitly enabled at assistant level)
            if tool_db.id in assistant_tool_overrides:
                is_enabled = assistant_tool_overrides[tool_db.id]
            else:
                is_enabled = False  # Tools OFF by default for assistants

            tool = MCPServerTool(
                id=tool_db.id,
                mcp_server_id=tool_db.mcp_server_id,
                name=tool_db.name,
                title=tool_db.title,
                description=tool_db.description,
                input_schema=tool_db.input_schema,
                meta=tool_db.meta,
                ui_resource_sha256=tool_db.ui_resource_sha256,
                is_enabled_by_default=is_enabled,  # Effective status after all overrides
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
                MCPServerToolSettingsTable.tenant_id == self.user.tenant_id,
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

        return {
            projection.assistant_id: self._project_assistant_mcp_server_tools(
                mcp_servers=deepcopy(list(projection.mcp_servers)),
                tools_db=tools_db,
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

    async def _get_assistants(self, space_id: UUID) -> Sequence[Assistants]:
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
            )
            .order_by(Assistants.created_at)
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
        prompts = prompt_records.all()

        for assistant in assistants:
            assistant.prompt = next(  # type: ignore[attr-defined]
                (
                    prompt
                    for prompt, assistant_id in prompts
                    if assistant_id == assistant.id
                ),
                None,
            )

        # For each assistant, load MCP servers with tools and apply space+assistant overrides
        for assistant in assistants:
            if assistant.mcp_servers:
                from eneo.mcp_servers.infrastructure.mappers.mcp_server_mapper import (
                    MCPServerMapper,
                )

                # Map to domain entities first
                mcp_servers = MCPServerMapper.to_entities(assistant.mcp_servers)

                # Apply space + assistant level overrides using same logic as space MCP loading
                mcp_servers = (
                    await self._load_assistant_mcp_server_tools_with_overrides(
                        space_id=space_id,
                        assistant_id=assistant.id,
                        mcp_servers=mcp_servers,
                    )
                )

                # Store the filtered entities back on the assistant for the factory
                setattr(assistant, "_mcp_server_entities", mcp_servers)

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
        """Load tools for MCP servers and apply tenant + space-level enablement overrides.

        Hierarchy:
        1. Tool default (is_enabled_by_default)
        2. Tenant override (mcp_server_tool_settings.is_enabled) - if exists
        3. Space override (spaces_mcp_server_tools.is_enabled) - if exists

        Rules:
        - If tenant disables a tool, it won't appear in space (filtered out)
        - Space can only override tools that are tenant-enabled
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
            MCPServerToolSettingsTable.tenant_id == self.user.tenant_id
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

        # Group tools by server
        from collections import defaultdict

        from eneo.mcp_servers.domain.entities.mcp_server import MCPServerTool

        tools_by_server: defaultdict[UUID, list[MCPServerTool]] = defaultdict(list)
        for tool_db in tools_db:
            # Determine effective is_enabled status
            # Priority: space override > tenant override > tool default
            tenant_enabled = tenant_tool_settings.get(
                tool_db.id, tool_db.is_enabled_by_default
            )

            # If tenant disabled this tool, skip it entirely (don't show in space)
            if (
                tool_db.id in tenant_tool_settings
                and not tenant_tool_settings[tool_db.id]
            ):
                continue

            # Apply space override if exists, otherwise use tenant/default
            if tool_db.id in space_tool_overrides:
                is_enabled = space_tool_overrides[tool_db.id]
            else:
                is_enabled = tenant_enabled

            tool = MCPServerTool(
                id=tool_db.id,
                mcp_server_id=tool_db.mcp_server_id,
                name=tool_db.name,
                title=tool_db.title,
                description=tool_db.description,
                input_schema=tool_db.input_schema,
                meta=tool_db.meta,
                ui_resource_sha256=tool_db.ui_resource_sha256,
                is_enabled_by_default=is_enabled,  # Effective status after overrides
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

    async def _get_from_query(self, query: sa.Select[tuple[Spaces]]) -> Space | None:
        entry_in_db = await self._get_record_with_options(query)
        if not entry_in_db:
            return

        space_ids = effective_space_ids_for(entry_in_db.id, entry_in_db.tenant_space_id)

        collections = await self._get_collections(space_ids)
        websites = await self._get_websites(space_ids)
        integration_knowledge_union = await self._get_integration_knowledge_union(
            space_ids
        )

        completion_models = await self.completion_model_repo.all(with_deprecated=True)
        embedding_models = await self.embedding_model_repo.all(with_deprecated=True)
        transcription_models = await self.transcription_model_repo.all(
            with_deprecated=True
        )

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
            .where(MCPServersTable.tenant_id == self.user.tenant_id)
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
        mcp_servers_result = await self.session.execute(mcp_servers_query)
        mcp_servers_db = mcp_servers_result.scalars().all()

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

        assistants = await self._get_assistants(space_id=entry_in_db.id)
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
            mcp_servers=mcp_servers,
            assistants_in_db=assistants,
            assistant_attachments=assistant_attachments,
            group_chats_in_db=group_chats,
            apps_in_db=apps,
            app_attachments=app_attachments,
            services_in_db=services,
            integration_knowledge_in_db=integration_knowledge_union,
            security_classification=entry_in_db.security_classification,
        )
        from eneo.mcp_servers.application.capability_resolver import (
            capability_availability,
        )

        space.available_capabilities = await capability_availability(
            self.session, self.user.tenant_id, space.security_classification
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

            personal_availability = await capability_availability(
                self.session,
                self.user.tenant_id,
                space.security_classification,
                user_group_ids=self.user.user_groups_ids,
                allowed_purposes=allowed_capability_purposes(self.user.permissions),
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
        await self.update_settings(
            entry_in_db.id,
            SpaceUpdate(
                completion_model_ids=[m.id for m in space.completion_models],
                embedding_model_ids=[m.id for m in space.embedding_models],
                transcription_model_ids=[m.id for m in space.transcription_models],
                mcp_server_ids=[server.id for server in space.mcp_servers],
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
        return query.where(Spaces.tenant_id == self.user.tenant_id)

    async def one_or_none(self, id: UUID) -> Optional[Space]:
        query = self._in_caller_tenant(sa.select(Spaces).where(Spaces.id == id))

        return await self._get_from_query(query)

    async def one(self, id: UUID) -> Space:
        space = await self.one_or_none(id=id)

        if space is None:
            raise NotFoundException()

        return space

    async def get_applications_projection(
        self, id: UUID
    ) -> SpaceApplicationsProjection:
        space_in_db = await self.session.scalar(
            sa.select(Spaces).where(Spaces.id == id)
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

    async def query(self, **filters: object) -> None:
        raise NotImplementedError()

    async def get_spaces_for_member(
        self, include_applications: bool = False
    ) -> list[Space]:
        user_id = self.user.id
        user_group_ids = (
            list(self.user.user_groups_ids) if self.user.user_groups_ids else []
        )

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
                    user=self.user,
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

        return await self._get_from_query(query)

    async def get_space_by_assistant(self, assistant_id: UUID) -> Space:
        query = self._in_caller_tenant(
            sa.select(Spaces).join(Assistants).where(Assistants.id == assistant_id)
        )

        space = await self._get_from_query(query)

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

    async def get_info_blob_read_access(
        self, info_blob: "InfoBlobInDB"
    ) -> list[SpaceAccessFacts]:
        """Reader memberships through the source's ownership and distribution.

        The inverse of what ``_get_from_query`` loads: a user may read a blob
        from any space they belong to that sees the blob's source, including
        child spaces of an organization the source is visible to. These facts
        cover membership-derived reads only; resource-scoped key IDs are omitted.
        """
        if info_blob.tenant_id != self.user.tenant_id:
            return []
        source, source_id = knowledge_source_for(info_blob)
        return await self.get_knowledge_source_read_access(source, source_id)

    async def get_knowledge_source_read_access(
        self, source: KnowledgeSource, source_id: UUID
    ) -> list[SpaceAccessFacts]:
        """Reader memberships for a source in this tenant, including distribution."""
        source_space_ids = source.spaces_seeing(source_id, self.user.tenant_id)
        user_group_ids = sa.select(UserGroups.id).where(
            UserGroups.id.in_(self.user.user_groups_ids),
            UserGroups.tenant_id == self.user.tenant_id,
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
                    SpacesUsers.user_id == self.user.id,
                ),
            )
            .where(
                Spaces.tenant_id == self.user.tenant_id,
                # Inverse of effective_space_ids_for: the space itself, or a
                # child space whose organization space sees the source.
                sa.or_(
                    Spaces.id.in_(source_space_ids),
                    Spaces.tenant_space_id.in_(source_space_ids),
                ),
                sa.or_(
                    Spaces.user_id == self.user.id,
                    SpacesUsers.user_id.is_not(None),
                    Spaces.group_members.any(group_membership),
                ),
            )
        )
        spaces = (await self.session.execute(query)).tuples().all()
        if not spaces:
            return []

        group_roles: dict[UUID, dict[UUID, SpaceRoleFact]] = {}
        if self.user.user_groups_ids:
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
                    {self.user.id: SpaceRoleFact(id=self.user.id, role=role)}
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
                source.table.tenant_id == self.user.tenant_id,
                Spaces.tenant_id == self.user.tenant_id,
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
        space = await self.session.scalar(
            sa.select(Spaces)
            .join(WebsitesTable, WebsitesTable.space_id == Spaces.id)
            .where(WebsitesTable.id == website_id)
            .where(WebsitesTable.tenant_id == self.user.tenant_id)
            .where(Spaces.tenant_id == self.user.tenant_id)
        )
        if space is None:
            raise NotFoundException("Website not found")

        member_rows = await self.session.execute(
            sa.select(SpacesUsers.user_id, SpacesUsers.role)
            .join(Users, Users.id == SpacesUsers.user_id)
            .where(
                SpacesUsers.space_id == space.id,
                SpacesUsers.user_id == self.user.id,
                Users.deleted_at.is_(None),
            )
        )
        group_rows = await self.session.execute(
            sa.select(SpacesUserGroups.user_group_id, SpacesUserGroups.role)
            .join(UserGroups, UserGroups.id == SpacesUserGroups.user_group_id)
            .where(SpacesUserGroups.space_id == space.id)
            .where(SpacesUserGroups.user_group_id.in_(self.user.user_groups_ids))
            .where(
                sa.or_(
                    UserGroups.state.is_(None),
                    UserGroups.state != UserGroupState.DELETED.value,
                )
            )
        )
        assistant_ids: Sequence[UUID] = ()
        app_ids: Sequence[UUID] = ()
        key = self.user.active_api_key
        if key is not None and key.scope_type == ApiKeyScopeType.ASSISTANT:
            assistant_ids = (
                await self.session.scalars(
                    sa.select(Assistants.id).where(
                        Assistants.space_id == space.id,
                        Assistants.id == key.scope_id,
                        Assistants.is_default.is_(False),
                    )
                )
            ).all()
        elif key is not None and key.scope_type == ApiKeyScopeType.APP:
            app_ids = (
                await self.session.scalars(
                    sa.select(Apps.id).where(
                        Apps.space_id == space.id, Apps.id == key.scope_id
                    )
                )
            ).all()
        return SpaceAccessFacts(
            id=space.id,
            tenant_id=space.tenant_id,
            user_id=space.user_id,
            tenant_space_id=space.tenant_space_id,
            members={id: SpaceRoleFact(id=id, role=role) for id, role in member_rows},
            group_members={
                id: SpaceRoleFact(id=id, role=role) for id, role in group_rows
            },
            # Website access never uses the default assistant's identity.
            default_assistant_id=None,
            assistant_ids=frozenset(assistant_ids),
            app_ids=frozenset(app_ids),
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
        self, space_ids: list[UUID]
    ) -> list[IntegrationKnowledge]:
        """Integration knowledge owned by the spaces or distributed to them."""
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
        return list(rows.scalars().all())

    async def get_space_by_name_and_tenant(
        self, name: str, tenant_id: UUID
    ) -> Space | None:
        q = sa.select(Spaces).where(
            Spaces.name == name,
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
        return await self._get_from_query(q)

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
