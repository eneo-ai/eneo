from typing import TYPE_CHECKING, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased, selectinload

from intric.ai_models.completion_models.completion_model import CompletionModelSparse
from intric.ai_models.embedding_models.embedding_model import EmbeddingModelSparse
from intric.database.database import AsyncSession
from intric.database.tables.ai_models_table import (
    CompletionModels,
    CompletionModelSettings,
    EmbeddingModels,
    EmbeddingModelSettings,
    TranscriptionModels,
    TranscriptionModelSettings,
)
from intric.database.tables.app_table import Apps, AppsFiles, AppsPrompts
from intric.database.tables.assistant_table import Assistants, AssistantsFiles
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.group_chats_table import (
    GroupChatsAssistantsMapping,
    GroupChatsTable,
)
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.database.tables.info_blobs_table import InfoBlobs as InfoBlobsTable
from intric.database.tables.integration_table import IntegrationKnowledge
from intric.database.tables.integration_table import (
    TenantIntegration as TenantIntegrationDBModel,
)
from intric.database.tables.integration_table import (
    UserIntegration as UserIntegrationDBModel,
)
from intric.database.tables.prompts_table import Prompts, PromptsAssistants
from intric.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from intric.database.tables.service_table import Services
from intric.database.tables.sessions_table import Sessions
from intric.database.tables.mcp_server_table import (
    MCPServers as MCPServersTable,
    MCPServerTools as MCPServerToolsTable,
    MCPServerToolSettings as MCPServerToolSettingsTable,
    SpacesMCPServers,
    SpacesMCPServerTools,
)
from intric.database.tables.spaces_table import (
    Spaces,
    SpacesCompletionModels,
    SpacesEmbeddingModels,
    SpacesTranscriptionModels,
    SpacesUsers,
)
from intric.database.tables.websites_table import CrawlRuns as CrawlRunsTable
from intric.database.tables.websites_table import Websites as WebsitesTable
from intric.main.exceptions import NotFoundException, UniqueException
from intric.spaces.api.space_models import SpaceMember
from intric.spaces.space import Space
from intric.spaces.space_factory import SpaceFactory
from intric.main.logging import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from intric.apps import AppRepository
    from intric.assistants.assistant import Assistant
    from intric.assistants.assistant_repo import AssistantRepository
    from intric.collections.domain.collection import Collection
    from intric.completion_models.domain.completion_model_repo import (
        CompletionModelRepository,
    )
    from intric.embedding_models.domain.embedding_model_repo import (
        EmbeddingModelRepository,
    )
    from intric.group_chat.domain.entities.group_chat import GroupChat
    from intric.mcp_servers.domain.entities.mcp_server import MCPServer
    from intric.transcription_models.domain.transcription_model_repo import (
        TranscriptionModelRepository,
    )
    from intric.users.user import UserInDB
    from intric.websites.domain.website import Website
    from intric.websites.infrastructure.http_auth_encryption import HttpAuthEncryptionService


class SpaceRepository:
    def __init__(
        self,
        session: AsyncSession,
        user: "UserInDB",
        factory: SpaceFactory,
        app_repo: Optional["AppRepository"],
        assistant_repo: "AssistantRepository",
        completion_model_repo: "CompletionModelRepository",
        transcription_model_repo: "TranscriptionModelRepository",
        embedding_model_repo: "EmbeddingModelRepository",
        http_auth_encryption: "HttpAuthEncryptionService",
    ):
        self.session = session
        self.user = user
        self.factory = factory
        self.app_repo = app_repo
        self.completion_model_repo = completion_model_repo
        self.transcription_model_repo = transcription_model_repo
        self.embedding_model_repo = embedding_model_repo
        self.assistant_repo = assistant_repo
        self.http_auth_encryption = http_auth_encryption

    def _options(self):
        return [
            selectinload(Spaces.members).selectinload(SpacesUsers.user),
            selectinload(Spaces.services).selectinload(Services.user),
            selectinload(Spaces.integration_knowledge_list).selectinload(
                IntegrationKnowledge.embedding_model
            ),
            selectinload(Spaces.integration_knowledge_list)
            .selectinload(IntegrationKnowledge.user_integration)
            .selectinload(UserIntegrationDBModel.tenant_integration)
            .selectinload(TenantIntegrationDBModel.integration),
            selectinload(Spaces.completion_models_mapping),
            selectinload(Spaces.embedding_models_mapping),
            selectinload(Spaces.transcription_models_mapping),
            selectinload(Spaces.mcp_servers_mapping),
            selectinload(Spaces.security_classification),
            selectinload(Spaces.security_classification).selectinload(
                SecurityClassificationDBModel.tenant
            ),
        ]

    async def _get_collections(self, space_id: UUID):
        query = (
            sa.select(
                CollectionsTable,
                sa.func.coalesce(sa.func.count(InfoBlobs.id).label("infoblob_count")),
            )
            .outerjoin(InfoBlobs, CollectionsTable.id == InfoBlobs.group_id)
            .where(CollectionsTable.space_id == space_id)
            .group_by(CollectionsTable.id)
            .order_by(CollectionsTable.created_at)
            .options(selectinload(CollectionsTable.embedding_model))
        )

        res = await self.session.execute(query)
        return res.all()

    async def _get_completion_models(self, space_in_db: Spaces):
        space_id = space_in_db.id
        tenant_id = space_in_db.tenant_id

        cm = aliased(CompletionModels)
        cms = aliased(CompletionModelSettings)
        scm = aliased(SpacesCompletionModels)

        stmt = (
            sa.select(cm, cms)
            .join(scm, scm.completion_model_id == cm.id)
            .outerjoin(
                cms,
                sa.and_(
                    cms.completion_model_id == cm.id,
                    cms.tenant_id == tenant_id,
                ),
            )
            .filter(scm.space_id == space_id)
            .order_by(cm.org, cm.created_at, cm.nickname)
        )

        res = await self.session.execute(stmt)
        return res.all()

    async def _get_embedding_models(self, space_in_db: Spaces):
        space_id = space_in_db.id
        tenant_id = space_in_db.tenant_id

        em = aliased(EmbeddingModels)
        ems = aliased(EmbeddingModelSettings)
        sem = aliased(SpacesEmbeddingModels)

        stmt = (
            sa.select(em, ems.is_org_enabled)
            .join(sem, sem.embedding_model_id == em.id)
            .outerjoin(
                ems,
                sa.and_(
                    ems.embedding_model_id == em.id,
                    ems.tenant_id == tenant_id,
                ),
            )
            .filter(sem.space_id == space_id)
        )

        res = await self.session.execute(stmt)
        return res.all()

    async def _get_transcription_models(self, space_in_db: Spaces):
        space_id = space_in_db.id
        tenant_id = space_in_db.tenant_id

        tm = aliased(TranscriptionModels)
        tms = aliased(TranscriptionModelSettings)
        stm = aliased(SpacesTranscriptionModels)

        stmt = (
            sa.select(tm, tms)
            .join(stm, stm.transcription_model_id == tm.id)
            .outerjoin(
                tms,
                sa.and_(
                    tms.transcription_model_id == tm.id,
                    tms.tenant_id == tenant_id,
                ),
            )
            .filter(stm.space_id == space_id)
        )

        res = await self.session.execute(stmt)
        return res.all()

    async def _set_embedding_models(
        self, space_in_db: Spaces, embedding_models: list[EmbeddingModelSparse]
    ):
        # Delete all
        stmt = sa.delete(SpacesEmbeddingModels).where(
            SpacesEmbeddingModels.space_id == space_in_db.id
        )
        await self.session.execute(stmt)

        if embedding_models:
            stmt = sa.insert(SpacesEmbeddingModels).values(
                [
                    dict(embedding_model_id=embedding_model.id, space_id=space_in_db.id)
                    for embedding_model in embedding_models
                ]
            )
            await self.session.execute(stmt)

    async def _set_completion_models(
        self, space_in_db: Spaces, completion_models: list[CompletionModelSparse]
    ):
        # Delete all
        stmt = sa.delete(SpacesCompletionModels).where(
            SpacesCompletionModels.space_id == space_in_db.id
        )
        await self.session.execute(stmt)

        if completion_models:
            stmt = sa.insert(SpacesCompletionModels).values(
                [
                    dict(completion_model_id=completion_model.id, space_id=space_in_db.id)
                    for completion_model in completion_models
                ]
            )
            await self.session.execute(stmt)

    async def _set_transcription_models(
        self, space_in_db: Spaces, transcription_models: list[TranscriptionModels]
    ):
        # Delete all
        stmt = sa.delete(SpacesTranscriptionModels).where(
            SpacesTranscriptionModels.space_id == space_in_db.id
        )
        await self.session.execute(stmt)

        if transcription_models:
            stmt = sa.insert(SpacesTranscriptionModels).values(
                [
                    dict(transcription_model_id=model.id, space_id=space_in_db.id)
                    for model in transcription_models
                ]
            )
            await self.session.execute(stmt)

    async def _set_mcp_servers(
        self, space_in_db: Spaces, mcp_servers: list["MCPServer"]
    ):
        # Delete all
        stmt = sa.delete(SpacesMCPServers).where(
            SpacesMCPServers.space_id == space_in_db.id
        )
        await self.session.execute(stmt)

        if mcp_servers:
            stmt = sa.insert(SpacesMCPServers).values(
                [
                    dict(mcp_server_id=server.id, space_id=space_in_db.id)
                    for server in mcp_servers
                ]
            )
            await self.session.execute(stmt)

    async def _set_mcp_tools(
        self, space_in_db: Spaces, tool_settings: list[tuple[UUID, bool]]
    ):
        """Set space-level tool enablement settings.

        Args:
            space_in_db: The space database object
            tool_settings: List of (tool_id, is_enabled) tuples
        """
        # Delete all existing settings
        stmt = sa.delete(SpacesMCPServerTools).where(
            SpacesMCPServerTools.space_id == space_in_db.id
        )
        await self.session.execute(stmt)

        if tool_settings:
            stmt = sa.insert(SpacesMCPServerTools).values(
                [
                    dict(
                        space_id=space_in_db.id,
                        mcp_server_tool_id=tool_id,
                        is_enabled=is_enabled
                    )
                    for tool_id, is_enabled in tool_settings
                ]
            )
            await self.session.execute(stmt)

    async def _set_members(self, space_in_db: Spaces, members: dict[UUID, SpaceMember]):
        # Delete all
        stmt = sa.delete(SpacesUsers).where(SpacesUsers.space_id == space_in_db.id)
        await self.session.execute(stmt)

        # Add members
        if members:
            spaces_users = [
                dict(
                    space_id=space_in_db.id,
                    user_id=member.id,
                    role=member.role.value,
                )
                for member in members.values()
            ]

            stmt = sa.insert(SpacesUsers).values(spaces_users)
            await self.session.execute(stmt)

        # This allows the newly added members to be reflected in the space
        await self.session.refresh(space_in_db)

    async def _set_assistants(self, space_in_db: Spaces, assistants: list["Assistant"]):
        new_assistants = [assistant for assistant in assistants if assistant.is_new]
        existing_assistants = [assistant for assistant in assistants if not assistant.is_new]

        for assistant in new_assistants:
            assistant.space_id = space_in_db.id
            await self.assistant_repo.add(assistant)

        for assistant in existing_assistants:
            assistant.space_id = space_in_db.id
            await self.assistant_repo.update(assistant)

        # Delete all assistants that are not in the list
        # Don't delete the default assistant
        stmt = (
            sa.delete(Assistants)
            .where(Assistants.space_id == space_in_db.id)
            .where(Assistants.id.notin_([assistant.id for assistant in assistants]))
            .where(Assistants.is_default == False)  # noqa
        )
        await self.session.execute(stmt)

    async def _set_default_assistant(self, space_in_db: Spaces, assistant: Optional["Assistant"]):
        if assistant is None:
            return

        # Unset all others
        stmt = (
            sa.update(Assistants)
            .values(is_default=False)
            .where(Assistants.space_id == space_in_db.id)
            .where(Assistants.id != assistant.id)
        )
        await self.session.execute(stmt)

        # Set the default to default
        stmt = sa.update(Assistants).values(is_default=True).where(Assistants.id == assistant.id)
        await self.session.execute(stmt)

    async def _set_group_chats(self, space_in_db: Spaces, group_chats: list["GroupChat"]):
        new_group_chats = [group_chat for group_chat in group_chats if group_chat.is_new]
        existing_group_chats = [group_chat for group_chat in group_chats if not group_chat.is_new]

        if new_group_chats:
            stmt = sa.insert(GroupChatsTable).values(
                [
                    dict(
                        id=group_chat.id,
                        name=group_chat.name,
                        space_id=space_in_db.id,
                        user_id=group_chat.user_id,
                        type="group-chat",
                        allow_mentions=group_chat.allow_mentions,
                        show_response_label=group_chat.show_response_label,
                        published=group_chat.published,
                        insight_enabled=group_chat.insight_enabled,
                    )
                    for group_chat in new_group_chats
                ]
            )
            await self.session.execute(stmt)

        for group_chat in existing_group_chats:
            stmt = (
                sa.update(GroupChatsTable)
                .values(
                    name=group_chat.name,
                    space_id=space_in_db.id,
                    allow_mentions=group_chat.allow_mentions,
                    show_response_label=group_chat.show_response_label,
                    published=group_chat.published,
                    insight_enabled=group_chat.insight_enabled,
                    metadata_json=group_chat.metadata_json,
                )
                .where(GroupChatsTable.id == group_chat.id)
            )

            await self.session.execute(stmt)

            # Delete all group chat assistants
            stmt = sa.delete(GroupChatsAssistantsMapping).where(
                GroupChatsAssistantsMapping.group_chat_id == group_chat.id
            )
            await self.session.execute(stmt)

            # Add new group chat assistants
            if group_chat.assistants:
                stmt = sa.insert(GroupChatsAssistantsMapping).values(
                    [
                        dict(
                            group_chat_id=group_chat.id,
                            assistant_id=group_chat_assistant.assistant.id,
                            user_description=group_chat_assistant.user_description,
                        )
                        for group_chat_assistant in group_chat.assistants
                    ]
                )
                await self.session.execute(stmt)

        # Delete all group chats that are not in the list
        stmt = (
            sa.delete(GroupChatsTable)
            .where(GroupChatsTable.space_id == space_in_db.id)
            .where(GroupChatsTable.id.notin_([group_chat.id for group_chat in group_chats]))
        )
        await self.session.execute(stmt)

    async def _set_collections(self, space_in_db: Spaces, collections: list["Collection"]):
        def _set_size_subquery(collection: "Collection"):
            stmt = (
                sa.select(sa.func.coalesce(sa.func.sum(InfoBlobsTable.size), 0))
                .where(InfoBlobsTable.group_id == collection.id)
                .scalar_subquery()
            )

            return stmt

        new_collections = [collection for collection in collections if collection.is_new]
        existing_collections = [collection for collection in collections if not collection.is_new]

        if new_collections:
            stmt = sa.insert(CollectionsTable).values(
                [
                    dict(
                        id=collection.id,
                        name=collection.name,
                        size=_set_size_subquery(collection),
                        tenant_id=collection.tenant_id,
                        user_id=collection.user_id,
                        embedding_model_id=collection.embedding_model.id,
                        space_id=space_in_db.id,
                    )
                    for collection in new_collections
                ]
            )
            await self.session.execute(stmt)

        for collection in existing_collections:
            stmt = (
                sa.update(CollectionsTable)
                .values(
                    name=collection.name,
                    size=_set_size_subquery(collection),
                    embedding_model_id=collection.embedding_model.id,
                    space_id=space_in_db.id,
                )
                .where(CollectionsTable.id == collection.id)
            )
            await self.session.execute(stmt)

        # Delete all collections that are not in the list
        stmt = (
            sa.delete(CollectionsTable)
            .where(CollectionsTable.space_id == space_in_db.id)
            .where(CollectionsTable.id.notin_([collection.id for collection in collections]))
        )
        await self.session.execute(stmt)

    async def _set_websites(self, space_in_db: Spaces, websites: list["Website"]):
        """Persist websites with encrypted auth credentials.

        Why: Repository is the encryption boundary. Domain entities have plaintext
        credentials, but database gets encrypted values.
        """
        def _set_size_subquery(website: "Website"):
            stmt = (
                sa.select(sa.func.coalesce(sa.func.sum(InfoBlobsTable.size), 0))
                .where(InfoBlobsTable.website_id == website.id)
                .scalar_subquery()
            )

            return stmt

        def _prepare_auth_fields(website: "Website") -> dict:
            """Encrypt HTTP auth credentials if present."""
            if website.http_auth:
                username, encrypted_password, auth_domain = \
                    self.http_auth_encryption.encrypt_credentials(website.http_auth)
                return {
                    'http_auth_username': username,
                    'encrypted_auth_password': encrypted_password,
                    'http_auth_domain': auth_domain,
                }
            else:
                return {
                    'http_auth_username': None,
                    'encrypted_auth_password': None,
                    'http_auth_domain': None,
                }

        new_websites = [website for website in websites if website.is_new]
        existing_websites = [website for website in websites if not website.is_new]

        if new_websites:
            values = []
            for website in new_websites:
                auth_fields = _prepare_auth_fields(website)
                values.append(dict(
                    id=website.id,
                    name=website.name,
                    url=website.url,
                    download_files=website.download_files,
                    crawl_type=website.crawl_type,
                    update_interval=website.update_interval,
                    size=_set_size_subquery(website),
                    tenant_id=website.tenant_id,
                    user_id=website.user_id,
                    embedding_model_id=website.embedding_model.id,
                    space_id=space_in_db.id,
                    **auth_fields,
                ))
            stmt = sa.insert(WebsitesTable).values(values)
            await self.session.execute(stmt)

        for website in existing_websites:
            auth_fields = _prepare_auth_fields(website)
            stmt = (
                sa.update(WebsitesTable)
                .values(
                    name=website.name,
                    url=website.url,
                    download_files=website.download_files,
                    crawl_type=website.crawl_type,
                    update_interval=website.update_interval,
                    size=_set_size_subquery(website),
                    embedding_model_id=website.embedding_model.id,
                    space_id=space_in_db.id,
                    **auth_fields,
                )
                .where(WebsitesTable.id == website.id)
            )
            await self.session.execute(stmt)

        # Delete all websites that are not in the list
        stmt = (
            sa.delete(WebsitesTable)
            .where(WebsitesTable.space_id == space_in_db.id)
            .where(WebsitesTable.id.notin_([website.id for website in websites]))
        )
        await self.session.execute(stmt)

    async def _load_assistant_mcp_server_tools_with_overrides(
        self, space_id: UUID, assistant_id: UUID, mcp_servers: list
    ) -> list:
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
        from intric.database.tables.assistant_table import AssistantMCPServerTools

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
        tools_db = tools_result.scalars().all()

        # Load tenant-level tool settings
        tenant_tool_settings_query = (
            sa.select(MCPServerToolSettingsTable)
            .where(MCPServerToolSettingsTable.tenant_id == self.user.tenant_id)
        )
        tenant_settings_result = await self.session.execute(tenant_tool_settings_query)
        tenant_settings_db = tenant_settings_result.scalars().all()

        # Create map: tool_id -> is_enabled (tenant level)
        tenant_tool_settings = {
            setting.mcp_server_tool_id: setting.is_enabled for setting in tenant_settings_db
        }

        # Load space-level tool overrides
        space_overrides_query = (
            sa.select(SpacesMCPServerTools).where(SpacesMCPServerTools.space_id == space_id)
        )
        space_overrides_result = await self.session.execute(space_overrides_query)
        space_overrides_db = space_overrides_result.scalars().all()

        # Create map: tool_id -> is_enabled (space level)
        space_tool_overrides = {
            override.mcp_server_tool_id: override.is_enabled for override in space_overrides_db
        }

        # Load assistant-level tool overrides
        assistant_overrides_query = (
            sa.select(AssistantMCPServerTools).where(
                AssistantMCPServerTools.assistant_id == assistant_id
            )
        )
        assistant_overrides_result = await self.session.execute(assistant_overrides_query)
        assistant_overrides_db = assistant_overrides_result.scalars().all()

        # Create map: tool_id -> is_enabled (assistant level)
        assistant_tool_overrides = {
            override.mcp_server_tool_id: override.is_enabled
            for override in assistant_overrides_db
        }

        # Group tools by server
        from collections import defaultdict

        from intric.mcp_servers.domain.entities.mcp_server import MCPServerTool

        tools_by_server = defaultdict(list)
        for tool_db in tools_db:
            # Determine effective is_enabled status
            # Priority: assistant override > space override > tenant override > tool default
            tenant_enabled = tenant_tool_settings.get(tool_db.id, tool_db.is_enabled_by_default)

            # If tenant disabled this tool, skip it entirely (don't show in space/assistant)
            if tool_db.id in tenant_tool_settings and not tenant_tool_settings[tool_db.id]:
                continue

            # Apply space override if exists, otherwise use tenant/default
            if tool_db.id in space_tool_overrides:
                space_enabled = space_tool_overrides[tool_db.id]
            else:
                space_enabled = tenant_enabled

            # If space disabled this tool, skip it (don't show in assistant)
            if not space_enabled:
                continue

            # Apply assistant override if exists, otherwise use space/tenant/default
            if tool_db.id in assistant_tool_overrides:
                is_enabled = assistant_tool_overrides[tool_db.id]
            else:
                is_enabled = space_enabled

            tool = MCPServerTool(
                id=tool_db.id,
                mcp_server_id=tool_db.mcp_server_id,
                name=tool_db.name,
                description=tool_db.description,
                input_schema=tool_db.input_schema,
                is_enabled_by_default=is_enabled,  # Effective status after all overrides
                created_at=tool_db.created_at,
                updated_at=tool_db.updated_at,
            )
            tools_by_server[tool_db.mcp_server_id].append(tool)

        # Attach tools to servers
        for server in mcp_servers:
            server.tools = tools_by_server.get(server.id, [])

        return mcp_servers

    async def _get_assistants(self, space_id: UUID):
        stmt = (
            sa.select(Assistants)
            .where(Assistants.space_id == space_id)
            .options(
                selectinload(Assistants.assistant_websites),
                selectinload(Assistants.assistant_groups),
                selectinload(Assistants.assistant_integration_knowledge),
                selectinload(Assistants.attachments).selectinload(AssistantsFiles.file),
                selectinload(Assistants.template),
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
            assistant.prompt = next(
                (prompt for prompt, assistant_id in prompts if assistant_id == assistant.id),
                None,
            )

        # For each assistant, load MCP servers with tools and apply space+assistant overrides
        for assistant in assistants:
            if assistant.mcp_servers:
                from intric.mcp_servers.infrastructure.mappers.mcp_server_mapper import (
                    MCPServerMapper,
                )

                # Map to domain entities first
                mcp_servers = MCPServerMapper.to_entities(assistant.mcp_servers)

                # Apply space + assistant level overrides using same logic as space MCP loading
                mcp_servers = await self._load_assistant_mcp_server_tools_with_overrides(
                    space_id=space_id, assistant_id=assistant.id, mcp_servers=mcp_servers
                )

                # Store the filtered entities back on the assistant for the factory
                assistant._mcp_server_entities = mcp_servers

        return assistants

    async def _get_services(self, space_id: UUID):
        # Fetch all services for the space
        stmt = (
            sa.select(Services)
            .where(Services.space_id == space_id)
            .options(
                selectinload(Services.service_groups),
                selectinload(Services.user),
            )
        )

        service_records = await self.session.execute(stmt)
        services_db = service_records.scalars().all()

        return services_db

    async def _get_group_chats(self, space_id: UUID):
        # Fetch all group chats for the space
        stmt = (
            sa.select(GroupChatsTable)
            .where(GroupChatsTable.space_id == space_id)
            .options(selectinload(GroupChatsTable.group_chat_assistants))
        )

        group_chat_records = await self.session.execute(stmt)
        group_chats_db = group_chat_records.scalars().all()

        return group_chats_db

    def _decrypt_website_auth(self, website_record: WebsitesTable) -> Optional:
        """Decrypt HTTP auth credentials from database record.

        Why: Repository is the encryption boundary - domain gets clean objects.

        Returns:
            HttpAuthCredentials if auth present and decryption succeeds, None otherwise.
        """

        if not (website_record.http_auth_username and
                website_record.encrypted_auth_password and
                website_record.http_auth_domain):
            return None

        try:
            return self.http_auth_encryption.decrypt_credentials(
                username=website_record.http_auth_username,
                encrypted_password=website_record.encrypted_auth_password,
                auth_domain=website_record.http_auth_domain
            )
        except ValueError as e:
            # Log decryption failure but don't fail entire website load
            logger.error(
                f"Failed to decrypt auth for website {website_record.id}: {str(e)}. "
                "Website will be loaded without auth.",
                extra={
                    "website_id": str(website_record.id),
                    "tenant_id": str(website_record.tenant_id),
                }
            )
            # Set transient flag for crawl task to detect
            # Why: Enables fail-fast behavior in crawler with clear error message
            website_record._auth_decrypt_failed = True
            return None

    async def _get_websites(self, space_id: UUID):
        """Fetch websites and decrypt their auth credentials.

        Why: Repository is the encryption boundary. We decrypt here and attach
        the plaintext credentials as a transient attribute on the record object.
        The factory then extracts this and passes it to Website.to_domain().
        """
        stmt = (
            sa.select(WebsitesTable)
            .where(WebsitesTable.space_id == space_id)
            .options(
                selectinload(WebsitesTable.latest_crawl).selectinload(CrawlRunsTable.job),
            )
        )

        website_records = await self.session.execute(stmt)
        websites_db = list(website_records.scalars())

        # Decrypt auth credentials and attach as transient attribute
        for website_record in websites_db:
            website_record._decrypted_http_auth = self._decrypt_website_auth(website_record)

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
        tools_db = tools_result.scalars().all()

        # Load tenant-level tool settings
        tenant_tool_settings_query = (
            sa.select(MCPServerToolSettingsTable)
            .where(MCPServerToolSettingsTable.tenant_id == self.user.tenant_id)
        )
        tenant_settings_result = await self.session.execute(tenant_tool_settings_query)
        tenant_settings_db = tenant_settings_result.scalars().all()

        # Create map: tool_id -> is_enabled (tenant level)
        tenant_tool_settings = {
            setting.mcp_server_tool_id: setting.is_enabled
            for setting in tenant_settings_db
        }

        # Load space-level tool overrides
        space_overrides_query = (
            sa.select(SpacesMCPServerTools)
            .where(SpacesMCPServerTools.space_id == space_id)
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
        from intric.mcp_servers.domain.entities.mcp_server import MCPServerTool

        tools_by_server = defaultdict(list)
        for tool_db in tools_db:
            # Determine effective is_enabled status
            # Priority: space override > tenant override > tool default
            tenant_enabled = tenant_tool_settings.get(tool_db.id, tool_db.is_enabled_by_default)

            # If tenant disabled this tool, skip it entirely (don't show in space)
            if tool_db.id in tenant_tool_settings and not tenant_tool_settings[tool_db.id]:
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
                description=tool_db.description,
                input_schema=tool_db.input_schema,
                is_enabled_by_default=is_enabled,  # Effective status after overrides
                created_at=tool_db.created_at,
                updated_at=tool_db.updated_at,
            )
            tools_by_server[tool_db.mcp_server_id].append(tool)

        # Attach tools to servers
        for server in mcp_servers:
            server.tools = tools_by_server.get(server.id, [])

        return mcp_servers

    async def _get_apps(self, space_id: UUID):
        stmt = (
            sa.select(Apps)
            .where(Apps.space_id == space_id)
            .options(
                selectinload(Apps.input_fields),
                selectinload(Apps.attachments).selectinload(AppsFiles.file),
                selectinload(Apps.template),
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
            app.prompt = next((prompt for prompt, app_id in prompts if app_id == app.id), None)

        return apps_db

    async def _get_from_query(self, query: sa.Select):
        entry_in_db = await self._get_record_with_options(query)

        if not entry_in_db:
            return

        collections = await self._get_collections(entry_in_db.id)
        websites = await self._get_websites(space_id=entry_in_db.id)

        completion_models = await self.completion_model_repo.all(with_deprecated=True)
        embedding_models = await self.embedding_model_repo.all(with_deprecated=True)
        transcription_models = await self.transcription_model_repo.all(with_deprecated=True)

        # Get tenant-enabled MCP servers directly
        mcp_servers_query = (
            sa.select(MCPServersTable)
            .where(MCPServersTable.tenant_id == self.user.tenant_id)
            .where(MCPServersTable.is_enabled == True)  # noqa: E712
        )
        mcp_servers_result = await self.session.execute(mcp_servers_query)
        mcp_servers_db = mcp_servers_result.scalars().all()

        # Convert to domain entities
        from intric.mcp_servers.domain.entities.mcp_server import MCPServer
        mcp_servers = [
            MCPServer(
                id=server.id,
                tenant_id=server.tenant_id,
                name=server.name,
                description=server.description,
                http_url=server.http_url,
                http_auth_type=server.http_auth_type,
                http_auth_config_schema=server.http_auth_config_schema,
                is_enabled=server.is_enabled,
                env_vars=server.env_vars,
                tags=server.tags,
                icon_url=server.icon_url,
                documentation_url=server.documentation_url,
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
        group_chats = await self._get_group_chats(space_id=entry_in_db.id)
        services = await self._get_services(space_id=entry_in_db.id)

        return self.factory.create_space_from_db(
            entry_in_db,
            user=self.user,
            collections_in_db=collections,
            websites_in_db=websites,
            completion_models=completion_models,
            embedding_models=embedding_models,
            transcription_models=transcription_models,
            mcp_servers=mcp_servers,
            assistants_in_db=assistants,
            group_chats_in_db=group_chats,
            apps_in_db=apps,
            services_in_db=services,
            security_classification=entry_in_db.security_classification,
        )

    async def _get_record_with_options(self, query):
        for option in self._options():
            query = query.options(option)

        return await self.session.scalar(query)

    async def _get_records_with_options(self, query):
        for option in self._options():
            query = query.options(option)

        return await self.session.scalars(query)

    async def add(self, space: Space) -> Space:
        query = (
            sa.insert(Spaces)
            .values(
                name=space.name,
                description=space.description,
                tenant_id=space.tenant_id,
                user_id=space.user_id,
            )
            .returning(Spaces)
        )

        try:
            entry_in_db = await self._get_record_with_options(query)
        except IntegrityError as e:
            raise UniqueException("Users can only have one personal space") from e

        await self._set_completion_models(entry_in_db, space.completion_models)
        await self._set_embedding_models(entry_in_db, space.embedding_models)
        await self._set_transcription_models(entry_in_db, space.transcription_models)
        await self._set_mcp_servers(entry_in_db, space.mcp_servers)
        await self._set_members(entry_in_db, space.members)
        await self._set_default_assistant(entry_in_db, space.default_assistant)
        await self._set_collections(entry_in_db, space.collections)
        await self._set_websites(entry_in_db, space.websites)
        await self._set_group_chats(entry_in_db, space.group_chats)
        return await self.one(id=entry_in_db.id)

    async def one_or_none(self, id: UUID) -> Optional[Space]:
        query = sa.select(Spaces).where(Spaces.id == id)

        return await self._get_from_query(query)

    async def one(self, id: UUID) -> Space:
        space = await self.one_or_none(id=id)

        if space is None:
            raise NotFoundException()

        return space

    async def update(
        self,
        space: Space,
        mcp_tool_settings: list[tuple[UUID, bool]] = None
    ) -> Space:
        query = (
            sa.update(Spaces)
            .values(
                name=space.name,
                description=space.description,
                security_classification_id=(
                    space.security_classification.id
                    if space.security_classification is not None
                    else None
                ),
            )
            .where(Spaces.id == space.id)
            .returning(Spaces)
        )
        entry_in_db = await self._get_record_with_options(query)

        await self._set_completion_models(entry_in_db, space.completion_models)
        await self._set_embedding_models(entry_in_db, space.embedding_models)
        await self._set_transcription_models(entry_in_db, space.transcription_models)
        await self._set_mcp_servers(entry_in_db, space.mcp_servers)
        if mcp_tool_settings is not None:
            await self._set_mcp_tools(entry_in_db, mcp_tool_settings)
        await self._set_members(entry_in_db, space.members)
        await self._set_default_assistant(entry_in_db, space.default_assistant)
        await self._set_collections(entry_in_db, space.collections)
        await self._set_websites(entry_in_db, space.websites)
        await self._set_assistants(
            entry_in_db,
            space.assistants + ([space.default_assistant] if space.default_assistant else []),
        )
        await self._set_group_chats(entry_in_db, space.group_chats)

        return await self.one(id=entry_in_db.id)

    async def delete(self, id: UUID):
        query = sa.delete(Spaces).where(Spaces.id == id)
        await self.session.execute(query)

    async def query(self, **filters):
        raise NotImplementedError()

    async def get_spaces_for_member(
        self, user_id: UUID, include_applications: bool = False
    ) -> list[Space]:
        query = (
            sa.select(Spaces)
            .join(SpacesUsers, Spaces.members)
            .where(SpacesUsers.user_id == user_id)
            .distinct()
            .order_by(Spaces.created_at)
        )

        records = await self._get_records_with_options(query)

        spaces = []
        for record in records:
            if include_applications:
                assistants = await self._get_assistants(space_id=record.id)
                apps = await self._get_apps(space_id=record.id)
            else:
                assistants = []
                apps = []

            spaces.append(
                self.factory.create_space_from_db(
                    record, user=self.user, assistants_in_db=assistants, apps_in_db=apps
                )
            )

        return spaces

    async def get_personal_space(self, user_id: UUID) -> Space:
        query = sa.select(Spaces).where(Spaces.user_id == user_id)

        return await self._get_from_query(query)

    async def get_space_by_assistant(self, assistant_id: UUID) -> Space:
        query = sa.select(Spaces).join(Assistants).where(Assistants.id == assistant_id)

        space = await self._get_from_query(query)

        if space is None:
            raise NotFoundException()

        return space

    async def get_space_by_app(self, app_id: UUID) -> Space:
        query = sa.select(Spaces).join(Apps).where(Apps.id == app_id)

        space = await self._get_from_query(query)

        if space is None:
            raise NotFoundException()

        return space

    async def get_space_by_service(self, service_id: UUID) -> Space:
        query = sa.select(Spaces).join(Services).where(Services.id == service_id)

        space = await self._get_from_query(query)

        if space is None:
            raise NotFoundException()

        return space

    async def get_space_by_group_chat(self, group_chat_id: UUID) -> Space:
        query = sa.select(Spaces).join(GroupChatsTable).where(GroupChatsTable.id == group_chat_id)
        space = await self._get_from_query(query=query)

        if space is None:
            raise NotFoundException()

        return space

    async def get_space_by_collection(self, collection_id: UUID) -> Space:
        query = sa.select(Spaces).join(CollectionsTable).where(CollectionsTable.id == collection_id)

        space = await self._get_from_query(query)

        if space is None:
            raise NotFoundException()

        return space

    async def get_space_by_website(self, website_id: UUID) -> Space:
        query = sa.select(Spaces).join(WebsitesTable).where(WebsitesTable.id == website_id)

        space = await self._get_from_query(query)

        if space is None:
            raise NotFoundException()

        return space

    async def get_space_by_integration_knowledge(self, integration_knowledge_id: UUID) -> Space:
        query = (
            sa.select(Spaces)
            .join(IntegrationKnowledge)
            .where(IntegrationKnowledge.id == integration_knowledge_id)
        )

        space = await self._get_from_query(query)

        if space is None:
            raise NotFoundException()

        return space

    async def get_space_by_session(self, session_id: UUID) -> Space:
        session_stmt = sa.select(Sessions).where(Sessions.id == session_id)
        session = await self.session.scalar(session_stmt)

        if session is None:
            raise NotFoundException(f"Session with ID {session_id} not found")

        # find space through assistant
        if session.assistant_id is not None:
            return await self.get_space_by_assistant(assistant_id=session.assistant_id)

        # find space through group chat
        if session.group_chat_id is not None:
            return await self.get_space_by_group_chat(group_chat_id=session.group_chat_id)
