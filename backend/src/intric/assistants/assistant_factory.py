from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from intric.ai_models.completion_models.completion_model import ModelKwargs
from intric.assistants.assistant import Assistant
from intric.completion_models.domain.completion_model import CompletionModel
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.prompts_table import Prompts
from intric.files.file_models import File
from intric.main.logging import get_logger
from intric.mcp_servers.infrastructure.mappers.mcp_server_mapper import MCPServerMapper
from intric.prompts.prompt_factory import PromptFactory
from intric.users.user import UserInDB, UserSparse

if TYPE_CHECKING:
    from intric.collections.domain.collection import Collection
    from intric.files.file_models import FileInfo
    from intric.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from intric.prompts.prompt import Prompt
    from intric.templates.assistant_template.assistant_template import AssistantTemplate
    from intric.templates.assistant_template.assistant_template_factory import (
        AssistantTemplateFactory,
    )
    from intric.websites.domain.website import Website
logger = get_logger(__name__)


class AssistantFactory:
    def __init__(
        self,
        prompt_factory: PromptFactory,
        assistant_template_factory: "AssistantTemplateFactory",
    ):
        self.prompt_factory = prompt_factory
        self.assistant_template_factory = assistant_template_factory

    def create_assistant(
        self,
        name: str,
        user: UserInDB,
        space_id: UUID,
        prompt: "Prompt" | None = None,
        completion_model: CompletionModel | None = None,
        completion_model_kwargs: ModelKwargs = ModelKwargs(),
        logging_enabled: bool = False,
        attachments: list["FileInfo"] | None = None,
        collections: list["Collection"] | None = None,
        integration_knowledge_list: list["IntegrationKnowledge"] | None = None,
        template: AssistantTemplate | None = None,
        is_default: bool = False,
        insight_enabled: bool = False,
        data_retention_days: int | None = None,
        metadata_json: dict | None = None,
    ) -> Assistant:
        return Assistant(
            id=None,
            user=user,
            space_id=space_id,
            name=name,
            prompt=prompt,
            completion_model=completion_model,
            completion_model_kwargs=completion_model_kwargs,
            attachments=attachments or [],
            logging_enabled=logging_enabled,
            websites=[],
            collections=collections or [],
            integration_knowledge_list=integration_knowledge_list or [],
            published=False,
            source_template=template,
            is_default=is_default,
            insight_enabled=insight_enabled,
            data_retention_days=data_retention_days,
            metadata_json=metadata_json,
        )

    def create_assistant_from_db(
        self,
        assistant_in_db: Assistants,
        completion_model: CompletionModel | None = None,
        completion_model_list: list[CompletionModel] = [],
        prompt: Prompts | None = None,
    ) -> Assistant:
        if completion_model is None and completion_model_list:
            completion_model = next(
                (
                    cm
                    for cm in completion_model_list
                    if cm.id == assistant_in_db.completion_model_id
                ),
                None,
            )

        if prompt is not None:
            prompt = self.prompt_factory.create_prompt_from_db(
                prompt_in_db=prompt, is_selected=True
            )

        attachments = [
            File(**attachment.file.to_dict()) for attachment in assistant_in_db.attachments
        ]

        user = UserSparse.model_validate(assistant_in_db.user)
        completion_model_kwargs = ModelKwargs.model_validate(
            assistant_in_db.completion_model_kwargs or {}
        )

        source_template = (
            self.assistant_template_factory.create_assistant_template(assistant_in_db.template)
            if assistant_in_db.template
            else None
        )

        return Assistant(
            id=assistant_in_db.id,
            user=user,
            space_id=assistant_in_db.space_id,
            name=assistant_in_db.name,
            prompt=prompt,
            completion_model=completion_model,
            completion_model_kwargs=completion_model_kwargs,
            attachments=attachments,
            logging_enabled=assistant_in_db.logging_enabled,
            websites=[],
            collections=[],
            integration_knowledge_list=[],
            mcp_servers=[],
            created_at=assistant_in_db.created_at,
            updated_at=assistant_in_db.updated_at,
            published=assistant_in_db.published,
            source_template=source_template,
            is_default=assistant_in_db.is_default,
            description=assistant_in_db.description,
            insight_enabled=assistant_in_db.insight_enabled,
        )

    def create_space_assistant_from_db(
        self,
        assistant_in_db: Assistants,
        completion_models: list[CompletionModel] = [],
        collections: list["Collection"] = [],
        websites: list["Website"] = [],
        integration_knowledge_list: list["IntegrationKnowledge"] = [],
        user: UserInDB = None,
    ) -> Assistant:
        user = UserSparse.model_validate(user)
        collection_ids = [
            assistant_collection.group_id
            for assistant_collection in assistant_in_db.assistant_groups
        ]
        websites_ids = [
            assistant_website.website_id for assistant_website in assistant_in_db.assistant_websites
        ]
        integration_knowledge_ids = [
            assistant_integration_knowledge.integration_knowledge_id
            for assistant_integration_knowledge in assistant_in_db.assistant_integration_knowledge
        ]

        prompt = None
        if assistant_in_db.prompt is not None:
            prompt = self.prompt_factory.create_prompt_from_db(
                prompt_in_db=assistant_in_db.prompt, is_selected=True
            )

        attachments = [
            File(**attachment.file.to_dict()) for attachment in assistant_in_db.attachments
        ]

        collections = [collection for collection in collections if collection.id in collection_ids]
        assistant_websites = [website for website in websites if website.id in websites_ids]

        integration_knowledge_list = [
            integration_knowledge
            for integration_knowledge in integration_knowledge_list
            if integration_knowledge.id in integration_knowledge_ids
        ]

        # Use filtered MCP servers if available (set by space repo), otherwise map from DB
        if hasattr(assistant_in_db, '_mcp_server_entities') and assistant_in_db._mcp_server_entities is not None:
            mcp_servers = assistant_in_db._mcp_server_entities
        else:
            # Fallback: Map MCP servers from database to domain entities (without filtering)
            mcp_servers = MCPServerMapper.to_entities(assistant_in_db.mcp_servers)

        completion_model_kwargs = ModelKwargs.model_validate(
            assistant_in_db.completion_model_kwargs or {}
        )
        completion_model = next(
            (cm for cm in completion_models if cm.id == assistant_in_db.completion_model_id),
            None,
        )

        source_template = (
            self.assistant_template_factory.create_assistant_template(assistant_in_db.template)
            if assistant_in_db.template
            else None
        )

        return Assistant(
            id=assistant_in_db.id,
            user=user,
            space_id=assistant_in_db.space_id,
            name=assistant_in_db.name,
            prompt=prompt,
            completion_model=completion_model,
            completion_model_kwargs=completion_model_kwargs,
            attachments=attachments,
            logging_enabled=assistant_in_db.logging_enabled,
            websites=assistant_websites,
            collections=collections,
            integration_knowledge_list=integration_knowledge_list,
            mcp_servers=mcp_servers,
            created_at=assistant_in_db.created_at,
            updated_at=assistant_in_db.updated_at,
            published=assistant_in_db.published,
            source_template=source_template,
            is_default=assistant_in_db.is_default,
            description=assistant_in_db.description,
            insight_enabled=assistant_in_db.insight_enabled,
            data_retention_days=assistant_in_db.data_retention_days,
            metadata_json=assistant_in_db.metadata_json,
        )
