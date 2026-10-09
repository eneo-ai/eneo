"""Validated write intent, independent of an assistant's runtime projection."""

from dataclasses import dataclass
from uuid import UUID

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.api.assistant_models import KnowledgeMode
from eneo.main.models import NOT_PROVIDED, NotProvided, is_provided
from eneo.mcp_servers.domain.capabilities import CapabilityPurpose
from eneo.prompts.prompt import Prompt


@dataclass(frozen=True, slots=True)
class AssistantUpdate:
    name: str | NotProvided = NOT_PROVIDED
    completion_model_id: UUID | None | NotProvided = NOT_PROVIDED
    completion_model_kwargs: ModelKwargs | NotProvided = NOT_PROVIDED
    logging_enabled: bool | NotProvided = NOT_PROVIDED
    published: bool | NotProvided = NOT_PROVIDED
    description: str | None | NotProvided = NOT_PROVIDED
    insight_enabled: bool | NotProvided = NOT_PROVIDED
    inline_file_text: bool | NotProvided = NOT_PROVIDED
    knowledge_mode: KnowledgeMode | NotProvided = NOT_PROVIDED
    data_retention_days: int | None | NotProvided = NOT_PROVIDED
    metadata_json: dict[str, object] | None | NotProvided = NOT_PROVIDED
    icon_id: UUID | None | NotProvided = NOT_PROVIDED
    prompt: Prompt | None = None
    collection_ids: list[UUID] | None = None
    website_ids: list[UUID] | None = None
    integration_knowledge_ids: list[UUID] | None = None
    attachments: list[tuple[UUID, bool]] | None = None
    enabled_capabilities: list[CapabilityPurpose] | None = None
    mcp_server_ids: list[UUID] | None = None
    mcp_tools: list[tuple[UUID, bool]] | None = None

    def scalar_values(self) -> dict[str, object]:
        values: dict[str, object] = {
            key: value
            for key, value in {
                "name": self.name,
                "completion_model_id": self.completion_model_id,
                "logging_enabled": self.logging_enabled,
                "published": self.published,
                "description": self.description,
                "insight_enabled": self.insight_enabled,
                "inline_file_text": self.inline_file_text,
                "knowledge_mode": self.knowledge_mode,
                "data_retention_days": self.data_retention_days,
                "metadata_json": self.metadata_json,
                "icon_id": self.icon_id,
            }.items()
            if is_provided(value)
        }
        if is_provided(self.completion_model_kwargs):
            values["completion_model_kwargs"] = (
                self.completion_model_kwargs.model_dump()
            )
        return values
