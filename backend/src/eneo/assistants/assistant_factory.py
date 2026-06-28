from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import Assistant
from eneo.completion_models.domain.completion_model import CompletionModel
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.prompts_table import Prompts
from eneo.files.file_models import File
from eneo.main.logging import get_logger
from eneo.mcp_servers.infrastructure.mappers.mcp_server_mapper import MCPServerMapper
from eneo.prompts.prompt_factory import PromptFactory
from eneo.users.user import UserInDB, UserSparse

if TYPE_CHECKING:
    from eneo.collections.domain.collection import Collection
    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from eneo.prompts.prompt import Prompt
    from eneo.templates.assistant_template.assistant_template import AssistantTemplate
    from eneo.templates.assistant_template.assistant_template_factory import (
        AssistantTemplateFactory,
    )
    from eneo.websites.domain.website import Website

logger = get_logger(__name__)


class AssistantFactory:
    def __init__(
        self,
        prompt_factory: PromptFactory,
        assistant_template_factory: "AssistantTemplateFactory",
    ):
        super().__init__()
        self.prompt_factory = prompt_factory
        self.assistant_template_factory = assistant_template_factory

    def create_assistant(
        self,
        name: str,
        user: UserInDB,
        space_id: UUID,
        prompt: Prompt | None = None,
        completion_model: CompletionModel | None = None,
        completion_model_kwargs: ModelKwargs | None = None,
        logging_enabled: bool = False,
        attachments: list["File"] | None = None,
        collections: list["Collection"] | None = None,
        integration_knowledge_list: list["IntegrationKnowledge"] | None = None,
        template: AssistantTemplate | None = None,
        is_default: bool = False,
        insight_enabled: bool = False,
        data_retention_days: int | None = None,
        metadata_json: dict[str, object] | None = None,
        description: str | None = None,
    ) -> Assistant:
        # Avoid mutable default anti-pattern
        if completion_model_kwargs is None:
            completion_model_kwargs = ModelKwargs()

        user_sparse = UserSparse.model_validate(user)

        return Assistant(
            id=None,
            user=user_sparse,
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
            description=description,
        )

    def create_assistant_from_db(
        self,
        assistant_in_db: Assistants,
        completion_model: CompletionModel | None = None,
        completion_model_list: Sequence[CompletionModel] | None = None,
        prompt: Prompts | None = None,
    ) -> Assistant:
        if completion_model is None and completion_model_list is not None:
            completion_model_list = list(completion_model_list)
            completion_model = next(
                (
                    cm
                    for cm in completion_model_list
                    if cm.id == assistant_in_db.completion_model_id
                ),
                None,
            )

        prompt_model: Prompt | None = None
        if prompt is not None:
            prompt_model = self.prompt_factory.create_prompt_from_db(
                prompt_in_db=prompt, is_selected=True
            )

        attachments = [
            File.model_validate(attachment.file)
            for attachment in assistant_in_db.attachments
        ]

        user = UserSparse.model_validate(assistant_in_db.user)
        # `is None` (not truthiness) so corrupt non-None JSONB still raises
        # ValidationError downstream rather than being silently dropped.
        if assistant_in_db.completion_model_kwargs is None:
            completion_model_kwargs = ModelKwargs()
        else:
            completion_model_kwargs_raw: dict[str, object] = (
                assistant_in_db.completion_model_kwargs
            )
            completion_model_kwargs = ModelKwargs.model_validate(
                completion_model_kwargs_raw
            )
        if completion_model is not None:
            completion_model_kwargs = completion_model_kwargs.filter_unsupported(
                completion_model.get_supported_model_kwargs()
            )

        source_template = (
            self.assistant_template_factory.create_assistant_template(
                assistant_in_db.template
            )
            if assistant_in_db.template
            else None
        )

        assert assistant_in_db.space_id is not None, "Assistants must belong to a space"
        return Assistant(
            id=assistant_in_db.id,
            user=user,
            space_id=assistant_in_db.space_id,
            name=assistant_in_db.name,
            prompt=prompt_model,
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
            icon_id=assistant_in_db.icon_id,
        )

    def create_space_assistant_from_db(
        self,
        assistant_in_db: Assistants,
        user: UserInDB,
        completion_models: Sequence[CompletionModel] | None = None,
        collections: Sequence["Collection"] | None = None,
        websites: Sequence["Website"] | None = None,
        integration_knowledge_list: Sequence["IntegrationKnowledge"] | None = None,
    ) -> Assistant:
        completion_models = list(completion_models or [])
        collections = list(collections or [])
        websites = list(websites or [])
        integration_knowledge_list = list(integration_knowledge_list or [])
        user_sparse = UserSparse.model_validate(user)
        collection_ids = [
            assistant_collection.group_id
            for assistant_collection in assistant_in_db.assistant_groups
        ]
        websites_ids = [
            assistant_website.website_id
            for assistant_website in assistant_in_db.assistant_websites
        ]
        integration_knowledge_ids = [
            assistant_integration_knowledge.integration_knowledge_id
            for assistant_integration_knowledge in assistant_in_db.assistant_integration_knowledge
        ]

        prompt = None
        if assistant_in_db.prompt is not None:  # type: ignore[attr-defined]
            prompt = self.prompt_factory.create_prompt_from_db(
                prompt_in_db=assistant_in_db.prompt,  # type: ignore[attr-defined]
                is_selected=True,
            )

        attachments = [
            File.model_validate(attachment.file)
            for attachment in assistant_in_db.attachments
        ]

        collections = [
            collection for collection in collections if collection.id in collection_ids
        ]
        assistant_websites = [
            website for website in websites if website.id in websites_ids
        ]

        integration_knowledge_list = [
            integration_knowledge
            for integration_knowledge in integration_knowledge_list
            if integration_knowledge.id in integration_knowledge_ids
        ]

        # Use filtered MCP servers if available (set by space repo), otherwise map from DB
        _mcp_server_entities = getattr(assistant_in_db, "_mcp_server_entities", None)
        if _mcp_server_entities is not None:
            mcp_servers = _mcp_server_entities
        else:
            # Fallback: Map MCP servers from database to domain entities (without filtering)
            mcp_servers = MCPServerMapper.to_entities(assistant_in_db.mcp_servers)

        # `is None` (not truthiness) so corrupt non-None JSONB still raises
        # ValidationError downstream rather than being silently dropped.
        if assistant_in_db.completion_model_kwargs is None:
            completion_model_kwargs = ModelKwargs()
        else:
            completion_model_kwargs_raw: dict[str, object] = (
                assistant_in_db.completion_model_kwargs
            )
            completion_model_kwargs = ModelKwargs.model_validate(
                completion_model_kwargs_raw
            )
        completion_model = next(
            (
                cm
                for cm in completion_models
                if cm.id == assistant_in_db.completion_model_id
            ),
            None,
        )
        if completion_model is not None:
            completion_model_kwargs = completion_model_kwargs.filter_unsupported(
                completion_model.get_supported_model_kwargs()
            )

        source_template = (
            self.assistant_template_factory.create_assistant_template(
                assistant_in_db.template
            )
            if assistant_in_db.template
            else None
        )

        assert assistant_in_db.space_id is not None, "Assistants must belong to a space"
        return Assistant(
            id=assistant_in_db.id,
            user=user_sparse,
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
            icon_id=assistant_in_db.icon_id,
        )
