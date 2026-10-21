"""Assistant update payloads: the API's typed command and the validated
write intent the repository persists, independent of an assistant's runtime
projection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.api.assistant_models import KnowledgeMode
from eneo.document_templates.domain import DocumentTemplateChoice
from eneo.main.models import NOT_PROVIDED, NotProvided, is_provided
from eneo.mcp_servers.domain.capabilities import CapabilityPurpose
from eneo.prompts.api.prompt_models import PromptCreate
from eneo.prompts.prompt import Prompt
from eneo.skills.domain.skill import SkillBindingIntent

AssistantUpdateField: TypeAlias = Literal[
    "name",
    "prompt",
    "completion_model_id",
    "completion_model_kwargs",
    "logging_enabled",
    "groups",
    "websites",
    "integration_knowledge_ids",
    "mcp_server_ids",
    "enabled_capabilities",
    "mcp_tools",
    "attachments",
    "description",
    "insight_enabled",
    "inline_file_text",
    "knowledge_mode",
    "data_retention_days",
    "metadata_json",
    "icon_id",
    "rerank_model_id",
    "skill_binding_intents",
    "document_template",
]

_SECURITY_RELEVANT_FIELDS: frozenset[AssistantUpdateField] = frozenset(
    {
        "completion_model_id",
        "groups",
        "websites",
        "integration_knowledge_ids",
        "mcp_server_ids",
        "rerank_model_id",
    }
)


class AssistantUpdateCaller(StrEnum):
    STANDALONE = "standalone"
    FLOW_MANAGED = "flow_managed"


class AssistantUpdateCommand(BaseModel):
    """Typed assistant update payload with field-set tracking."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    prompt: PromptCreate | None = None
    completion_model_id: UUID | None | NotProvided = Field(default=NOT_PROVIDED)
    completion_model_kwargs: ModelKwargs | None = None
    logging_enabled: bool | None = None
    groups: list[UUID] | None = None
    websites: list[UUID] | None = None
    integration_knowledge_ids: list[UUID] | None = None
    mcp_server_ids: list[UUID] | None = None
    enabled_capabilities: list[CapabilityPurpose] | None = None
    mcp_tools: list[tuple[UUID, bool]] | None = None
    attachments: list[tuple[UUID, bool]] | None = None
    description: str | None | NotProvided = Field(default=NOT_PROVIDED)
    insight_enabled: bool | None = None
    inline_file_text: bool | None = None
    knowledge_mode: KnowledgeMode | None = None
    data_retention_days: int | None | NotProvided = Field(default=NOT_PROVIDED)
    metadata_json: dict[str, object] | None | NotProvided = Field(default=NOT_PROVIDED)
    icon_id: UUID | None | NotProvided = Field(default=NOT_PROVIDED)
    rerank_model_id: UUID | None | NotProvided = Field(default=NOT_PROVIDED)
    skill_binding_intents: list[SkillBindingIntent] | None = None
    document_template: DocumentTemplateChoice | None = None

    def is_set(self, field_name: AssistantUpdateField) -> bool:
        return field_name in self.model_fields_set

    def changed_security_field_names(self) -> frozenset[AssistantUpdateField]:
        return frozenset(
            field
            for field in _SECURITY_RELEVANT_FIELDS
            if field in self.model_fields_set
        )


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
    rerank_model_id: UUID | None | NotProvided = NOT_PROVIDED
    prompt: Prompt | None = None
    document_template: DocumentTemplateChoice | None = None
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
                "rerank_model_id": self.rerank_model_id,
            }.items()
            if is_provided(value)
        }
        if is_provided(self.completion_model_kwargs):
            values["completion_model_kwargs"] = (
                self.completion_model_kwargs.model_dump()
            )
        return values
