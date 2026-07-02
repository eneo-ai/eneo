from __future__ import annotations

from enum import StrEnum
from typing import Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.main.models import NOT_PROVIDED, NotProvided
from eneo.prompts.api.prompt_models import PromptCreate

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
    "mcp_tools",
    "attachment_ids",
    "description",
    "insight_enabled",
    "data_retention_days",
    "metadata_json",
    "icon_id",
]

_SECURITY_RELEVANT_FIELDS: frozenset[AssistantUpdateField] = frozenset(
    {
        "completion_model_id",
        "groups",
        "websites",
        "integration_knowledge_ids",
        "mcp_server_ids",
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
    mcp_tools: list[tuple[UUID, bool]] | None = None
    attachment_ids: list[UUID] | None = None
    description: str | None | NotProvided = Field(default=NOT_PROVIDED)
    insight_enabled: bool | None = None
    data_retention_days: int | None | NotProvided = Field(default=NOT_PROVIDED)
    metadata_json: dict[str, object] | None | NotProvided = Field(default=NOT_PROVIDED)
    icon_id: UUID | None | NotProvided = Field(default=NOT_PROVIDED)

    def is_set(self, field_name: AssistantUpdateField) -> bool:
        return field_name in self.model_fields_set

    def changed_security_field_names(self) -> frozenset[AssistantUpdateField]:
        return frozenset(
            field
            for field in _SECURITY_RELEVANT_FIELDS
            if field in self.model_fields_set
        )
