from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.assistants.assistant import Assistant
from intric.assistants.assistant_factory import AssistantFactory
from intric.database.database import AsyncSession
from intric.database.tables.assistant_table import (
    AssistantIntegrationKnowledge,
    AssistantMCPServers,
    Assistants,
    AssistantsFiles,
    AssistantsGroups,
    AssistantsWebsites,
)
from intric.database.tables.assistant_template_table import AssistantTemplates
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.database.tables.integration_table import IntegrationKnowledge
from intric.database.tables.integration_table import (
    TenantIntegration as TenantIntegrationDBModel,
)
from intric.database.tables.integration_table import (
    UserIntegration as UserIntegrationDBModel,
)
from intric.database.tables.prompts_table import Prompts, PromptsAssistants
from intric.database.tables.users_table import Users
from intric.database.tables.websites_table import CrawlRuns, Websites
from intric.files.file_models import FileInfo
from intric.prompts.prompt import Prompt

if TYPE_CHECKING:
    from intric.collections.domain.collection import Collection
    from intric.completion_models.domain.completion_model_repo import (
        CompletionModelRepository,
    )
    from intric.users.user import UserInDB
    from intric.websites.domain.website import Website


class AssistantRepository:
    def __init__(
        self,
        session: AsyncSession,
        factory: AssistantFactory,
        completion_model_repo: "CompletionModelRepository",
        user: "UserInDB",
    ):
        self.session = session
        self.factory = factory
        self.completion_model_repo = completion_model_repo
        self.user = user

    @staticmethod
    def _options():
        return [
            selectinload(Assistants.user).selectinload(Users.tenant),
            selectinload(Assistants.user).selectinload(Users.roles),
            selectinload(Assistants.user).selectinload(Users.predefined_roles),
            selectinload(Assistants.websites)
            .selectinload(Websites.latest_crawl)
            .selectinload(CrawlRuns.job),
            selectinload(Assistants.websites).selectinload(Websites.embedding_model),
            selectinload(Assistants.attachments).selectinload(AssistantsFiles.file),
            selectinload(Assistants.template).selectinload(AssistantTemplates.completion_model),
            selectinload(Assistants.integration_knowledge_list).selectinload(
                IntegrationKnowledge.embedding_model
            ),
            selectinload(Assistants.integration_knowledge_list)
            .selectinload(IntegrationKnowledge.user_integration)
            .selectinload(UserIntegrationDBModel.tenant_integration)
            .selectinload(TenantIntegrationDBModel.integration),
            selectinload(Assistants.mcp_servers),
            selectinload(Assistants.assistant_mcp_server_tools),
        ]

    async def _set_is_selected_to_false(self, assistant_id: UUID):
        stmt = (
            sa.update(PromptsAssistants)
            .values(is_selected=False)
            .where(PromptsAssistants.assistant_id == assistant_id)
        )

        await self.session.execute(stmt)

    async def _add_assistant_prompt_entry(self, assistant_id: UUID, prompt_id: UUID):
        stmt = (
            sa.insert(PromptsAssistants)
            .values(assistant_id=assistant_id, prompt_id=prompt_id, is_selected=True)
            .returning(PromptsAssistants)
        )

        return await self.session.scalar(stmt)

    async def _get_assistant_prompt_entry(self, assistant_id: UUID, prompt_id: UUID):
        stmt = (
            sa.select(PromptsAssistants)
            .where(PromptsAssistants.prompt_id == prompt_id)
            .where(PromptsAssistants.assistant_id == assistant_id)
        )

        return await self.session.scalar(stmt)

    async def _select_assistant_prompt_entry(self, assistant_id: UUID, prompt_id: UUID):
        stmt = (
            sa.update(PromptsAssistants)
            .where(PromptsAssistants.prompt_id == prompt_id)
            .where(PromptsAssistants.assistant_id == assistant_id)
            .values(is_selected=True)
        )

        await self.session.execute(stmt)

    async def _add_prompt(self, assistant_id: UUID, prompt: Prompt):
        await self._set_is_selected_to_false(assistant_id=assistant_id)

        prompt_assistant_entry = await self._get_assistant_prompt_entry(
            assistant_id=assistant_id, prompt_id=prompt.id
        )

        if prompt_assistant_entry is not None:
            await self._select_assistant_prompt_entry(
                assistant_id=assistant_id, prompt_id=prompt.id
            )
        else:
            await self._add_assistant_prompt_entry(assistant_id=assistant_id, prompt_id=prompt.id)

        return prompt

    async def _get_selected_prompt(self, assistant_id: UUID):
        stmt = (
            sa.select(Prompts)
            .join(PromptsAssistants)
            .where(PromptsAssistants.prompt_id == Prompts.id)
            .where(PromptsAssistants.assistant_id == assistant_id)
            .where(PromptsAssistants.is_selected)
            .options(selectinload(Prompts.user))
        )

        return await self.session.scalar(stmt)

    async def _set_attachments(self, assistant_in_db: Assistants, attachments: list[FileInfo]):
        # Delete all
        stmt = sa.delete(AssistantsFiles).where(AssistantsFiles.assistant_id == assistant_in_db.id)
        await self.session.execute(stmt)

        # Add attachments
        if attachments:
            attachments_dicts = [
                dict(assistant_id=assistant_in_db.id, file_id=file.id) for file in attachments
            ]

            stmt = sa.insert(AssistantsFiles).values(attachments_dicts)
            await self.session.execute(stmt)

        await self.session.refresh(assistant_in_db)

    async def _set_collections(self, assistant_in_db: Assistants, collections: list["Collection"]):
        # Delete all
        stmt = sa.delete(AssistantsGroups).where(
            AssistantsGroups.assistant_id == assistant_in_db.id
        )
        await self.session.execute(stmt)

        if collections:
            stmt = sa.insert(AssistantsGroups).values(
                [dict(group_id=group.id, assistant_id=assistant_in_db.id) for group in collections]
            )
            await self.session.execute(stmt)

        await self.session.refresh(assistant_in_db)

    async def _set_websites(self, assistant_in_db: Assistants, websites: list["Website"]):
        # Delete all
        stmt = sa.delete(AssistantsWebsites).where(
            AssistantsWebsites.assistant_id == assistant_in_db.id
        )
        await self.session.execute(stmt)

        if websites:
            stmt = sa.insert(AssistantsWebsites).values(
                [
                    dict(website_id=website.id, assistant_id=assistant_in_db.id)
                    for website in websites
                ]
            )
            await self.session.execute(stmt)

        await self.session.refresh(assistant_in_db)

    async def _set_integration_knowledge(
        self,
        assistant_in_db: Assistants,
        integration_knowledge: list[AssistantIntegrationKnowledge],
    ):
        # Delete all
        stmt = sa.delete(AssistantIntegrationKnowledge).where(
            AssistantIntegrationKnowledge.assistant_id == assistant_in_db.id
        )
        await self.session.execute(stmt)

        if integration_knowledge:
            stmt = sa.insert(AssistantIntegrationKnowledge).values(
                [
                    dict(
                        integration_knowledge_id=knowledge.id,
                        assistant_id=assistant_in_db.id,
                    )
                    for knowledge in integration_knowledge
                ]
            )
            await self.session.execute(stmt)

        await self.session.refresh(assistant_in_db)

    async def _set_mcp_servers(
        self,
        assistant_in_db: Assistants,
        mcp_server_ids: list[UUID],
    ):
        """Set MCP server associations for an assistant.

        Args:
            assistant_in_db: The assistant database record
            mcp_server_ids: List of MCP server IDs to associate
        """
        # Delete all existing associations
        stmt = sa.delete(AssistantMCPServers).where(
            AssistantMCPServers.assistant_id == assistant_in_db.id
        )
        await self.session.execute(stmt)

        if mcp_server_ids:
            values = [
                {
                    "assistant_id": assistant_in_db.id,
                    "mcp_server_id": server_id,
                }
                for server_id in mcp_server_ids
            ]

            stmt = sa.insert(AssistantMCPServers).values(values)
            await self.session.execute(stmt)

        await self.session.refresh(assistant_in_db)

    async def _set_mcp_tools(
        self,
        assistant_in_db: Assistants,
        mcp_tool_settings: list[tuple[UUID, bool]],
    ):
        """Set MCP tool overrides for an assistant.

        Args:
            assistant_in_db: The assistant database record
            mcp_tool_settings: List of (tool_id, is_enabled) tuples
        """
        from intric.database.tables.assistant_table import AssistantMCPServerTools

        # Delete all existing tool overrides
        stmt = sa.delete(AssistantMCPServerTools).where(
            AssistantMCPServerTools.assistant_id == assistant_in_db.id
        )
        await self.session.execute(stmt)

        if mcp_tool_settings:
            values = [
                {
                    "assistant_id": assistant_in_db.id,
                    "mcp_server_tool_id": tool_id,
                    "is_enabled": is_enabled,
                }
                for tool_id, is_enabled in mcp_tool_settings
            ]

            stmt = sa.insert(AssistantMCPServerTools).values(values)
            await self.session.execute(stmt)

        await self.session.refresh(assistant_in_db)

    async def _get_groups(self, assistant_id: UUID):
        query = (
            sa.select(
                CollectionsTable,
                sa.func.coalesce(sa.func.count(InfoBlobs.id).label("infoblob_count")),
            )
            .outerjoin(InfoBlobs, CollectionsTable.id == InfoBlobs.group_id)
            .outerjoin(AssistantsGroups, AssistantsGroups.group_id == CollectionsTable.id)
            .where(AssistantsGroups.assistant_id == assistant_id)
            .group_by(CollectionsTable.id)
            .order_by(CollectionsTable.created_at)
            .options(selectinload(CollectionsTable.embedding_model))
        )

        res = await self.session.execute(query)
        return res.all()

    async def get_record_with_options(self, query):
        for option in self._options():
            query = query.options(option)

        return await self.session.scalar(query)

    async def get_records_with_options(self, query):
        for option in self._options():
            query = query.options(option)

        return await self.session.scalars(query)

    async def add(self, assistant: Assistant):
        completion_model_id = (
            assistant.completion_model.id if assistant.completion_model is not None else None
        )

        template_id = assistant.source_template.id if assistant.source_template else None
        query = (
            sa.insert(Assistants)
            .values(
                id=assistant.id,
                name=assistant.name,
                user_id=assistant.user.id,
                completion_model_id=completion_model_id,
                completion_model_kwargs=assistant.completion_model_kwargs.model_dump(),
                logging_enabled=assistant.logging_enabled,
                guardrail_active=False,
                space_id=assistant.space_id,
                is_default=assistant.is_default,
                published=assistant.published,
                template_id=template_id,
                type=assistant.type,
                description=assistant.description,
            )
            .returning(Assistants)
        )
        entry_in_db = await self.session.scalar(query)

        # Assign groups and websites
        await self._set_collections(entry_in_db, assistant.collections)
        await self._set_websites(entry_in_db, assistant.websites)
        await self._set_attachments(entry_in_db, attachments=assistant.attachments)

        if assistant.prompt:
            await self._add_prompt(assistant_id=entry_in_db.id, prompt=assistant.prompt)

    async def get_for_user(self, user_id: UUID, search_query: str = None):
        query = (
            sa.select(Assistants)
            .where(Assistants.user_id == user_id)
            .order_by(Assistants.created_at)
        )

        if search_query is not None:
            query = query.filter(Assistants.name.like(f"%{search_query}%"))

        records = await self.get_records_with_options(query)

        completion_models = await self.completion_model_repo.all()

        return [
            self.factory.create_assistant_from_db(record, completion_model_list=completion_models)
            for record in records
        ]

    async def get_for_tenant(
        self,
        tenant_id: UUID,
        search_query: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
    ):
        query = (
            sa.select(Assistants)
            .join(Users)
            .where(Users.tenant_id == tenant_id)
            .order_by(Assistants.created_at)
        )

        if start_date is not None:
            query = query.filter(Assistants.created_at >= start_date)

        if end_date is not None:
            query = query.filter(Assistants.created_at <= end_date)

        if search_query is not None:
            query = query.filter(Assistants.name.like(f"%{search_query}%"))

        records = await self.get_records_with_options(query)
        completion_models = await self.completion_model_repo.all()

        return [
            self.factory.create_assistant_from_db(record, completion_model_list=completion_models)
            for record in records
        ]

    async def update(self, assistant: Assistant):
        query = (
            sa.update(Assistants)
            .values(
                name=assistant.name,
                completion_model_id=assistant.completion_model.id,
                completion_model_kwargs=assistant.completion_model_kwargs.model_dump(),
                logging_enabled=assistant.logging_enabled,
                space_id=assistant.space_id,
                published=assistant.published,
                description=assistant.description,
                type=assistant.type,
                insight_enabled=assistant.insight_enabled,
                data_retention_days=assistant.data_retention_days,
                metadata_json=assistant.metadata_json,
            )
            .where(Assistants.id == assistant.id)
            .returning(Assistants)
        )
        entry_in_db = await self.session.scalar(query)

        # assign groups and websites
        await self._set_collections(entry_in_db, assistant.collections)
        await self._set_websites(entry_in_db, assistant.websites)
        await self._set_integration_knowledge(entry_in_db, assistant.integration_knowledge_list)
        await self._set_attachments(entry_in_db, assistant.attachments)

        # Set MCP servers if provided
        if hasattr(assistant, '_mcp_server_ids') and assistant._mcp_server_ids is not None:
            await self._set_mcp_servers(entry_in_db, assistant._mcp_server_ids)

        # Set MCP tool overrides if provided
        if hasattr(assistant, '_mcp_tool_settings') and assistant._mcp_tool_settings is not None:
            await self._set_mcp_tools(entry_in_db, assistant._mcp_tool_settings)

        if assistant.prompt:
            await self._add_prompt(assistant_id=entry_in_db.id, prompt=assistant.prompt)
