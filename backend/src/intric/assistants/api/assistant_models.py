from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import AsyncIterable, Optional, Union
from uuid import UUID

from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    computed_field,
    field_validator,
)
from typing_extensions import TypedDict

from intric.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelPublic,
    CompletionModelSparse,
    ModelKwargs,
)
from intric.ai_models.embedding_models.embedding_model import EmbeddingModelLegacy
from intric.collections.presentation.collection_models import CollectionPublic
from intric.completion_models.domain.completion_model import CompletionModel
from intric.completion_models.infrastructure.web_search import WebSearchResult
from intric.files.file_models import File, FilePublic, FileRestrictions
from intric.groups_legacy.api.group_models import GroupInDBBase
from intric.info_blobs.info_blob import InfoBlobInDBWithScore
from intric.integration.presentation.models import IntegrationKnowledgePublic
from intric.main.models import (
    NOT_PROVIDED,
    InDB,
    MCPToolSetting,
    ModelId,
    NotProvided,
    ResourcePermissionsMixin,
    partial_model,
)
from intric.prompts.api.prompt_models import PromptCreate, PromptPublic
from intric.questions.question import UseTools
from intric.sessions.session import SessionInDB
from intric.users.user import UserSparse
from intric.websites.presentation.website_models import WebsitePublic


class AssistantType(str, Enum):
    ASSISTANT = "assistant"
    DEFAULT_ASSISTANT = "default-assistant"


class ModelInfo(BaseModel):
    """Information about the model used by the assistant."""

    name: str
    max_input_tokens: int
    max_output_tokens: int
    prompt_tokens: Optional[int] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def token_limit(self) -> int:
        """Backward-compat: exposed in JSON responses for frontend."""
        return self.max_input_tokens


# Relationship models
class GroupWithEmbeddingModel(GroupInDBBase):
    embedding_model: Optional[EmbeddingModelLegacy] = None


# Models
class AssistantGuard(BaseModel):
    guardrail_active: bool = True
    guardrail_string: str = ""
    on_fail_message: str = "Jag kan tyvärr inte svara på det. Fråga gärna något annat!"


class MCPServerPublicDict(TypedDict):
    id: str
    name: str
    description: str | None
    http_url: str | None
    http_auth_type: str | None
    tags: list[str] | None
    icon_url: str | None
    security_classification: dict[str, object] | None
    tools: list[dict[str, object]]


def _empty_uuid_list() -> list[UUID]:
    return []


def _empty_mcp_server_public_dict_list() -> list[MCPServerPublicDict]:
    return []


def _empty_mcp_tool_setting_list() -> list[MCPToolSetting]:
    return []


class EffectiveConfigPublic(BaseModel):
    """Frontend hint surface for personal-assistant governance.

    Only meaningful on default assistants in personal spaces. `prompt_locked`
    is exposed as a boolean — we never leak the admin-prompt text to the
    user-facing API.
    """

    models_enforced: bool
    available_models: list[CompletionModelSparse]
    locked_model: CompletionModelSparse | None
    default_model: CompletionModelSparse | None
    mcp_enforced: bool
    available_mcp_servers: list[MCPServerPublicDict] = Field(
        default_factory=_empty_mcp_server_public_dict_list  # type: ignore[arg-type]
    )
    # Allowed servers that start switched OFF in the user's chat (UX seed
    # only — the user can still enable them per conversation).
    default_disabled_mcp_server_ids: list[UUID] = Field(
        default_factory=_empty_uuid_list
    )
    prompt_locked: bool


class AssistantBase(BaseModel):
    name: str
    completion_model_kwargs: ModelKwargs | None = Field(default_factory=ModelKwargs)
    logging_enabled: bool | None = False

    @field_validator("completion_model_kwargs", mode="before")
    @classmethod
    def set_model_kwargs(cls, model_kwargs: ModelKwargs | None):
        # `default_factory` does not fire for explicit None; coerce here so
        # legacy NULL JSONB rows load. `is None` (not truthiness) so a
        # corrupt non-None value still raises ValidationError.
        if model_kwargs is None:
            return ModelKwargs()
        return model_kwargs


_DEPRECATED_DESCRIPTION = "This field is deprecated and will be ignored"
_DEPRECATED_JSON_SCHEMA: dict[str, JsonValue] = {"deprecated": True}


# Pydantic v2 emits UnsupportedFieldAttributeWarning when `deprecated=True` is
# attached to a `Field()` on a Union (incl. Optional). Routing the flag through
# `json_schema_extra` keeps the OpenAPI spec marking the field deprecated.
class AssistantCreatePublic(AssistantBase):
    space_id: UUID
    prompt: Optional[PromptCreate] = Field(
        default=None,
        description=_DEPRECATED_DESCRIPTION,
        json_schema_extra=_DEPRECATED_JSON_SCHEMA,
    )
    groups: list[ModelId] = Field(
        default_factory=lambda: list[ModelId](),
        description=_DEPRECATED_DESCRIPTION,
        json_schema_extra=_DEPRECATED_JSON_SCHEMA,
    )
    websites: list[ModelId] = Field(
        default_factory=lambda: list[ModelId](),
        description=_DEPRECATED_DESCRIPTION,
        json_schema_extra=_DEPRECATED_JSON_SCHEMA,
    )
    integration_knowledge_list: list[ModelId] = Field(
        default_factory=lambda: list[ModelId](),
        description=_DEPRECATED_DESCRIPTION,
        json_schema_extra=_DEPRECATED_JSON_SCHEMA,
    )
    mcp_servers: list[ModelId] = Field(
        default_factory=lambda: list[ModelId](),
        description=_DEPRECATED_DESCRIPTION,
        json_schema_extra=_DEPRECATED_JSON_SCHEMA,
    )
    guardrail: Optional[AssistantGuard] = Field(
        default=None,
        description=_DEPRECATED_DESCRIPTION,
        json_schema_extra=_DEPRECATED_JSON_SCHEMA,
    )
    completion_model: Optional[ModelId] = Field(
        default=None,
        description=_DEPRECATED_DESCRIPTION,
        json_schema_extra=_DEPRECATED_JSON_SCHEMA,
    )
    logging_enabled: Optional[bool] = Field(
        default=None,
        description=_DEPRECATED_DESCRIPTION,
        json_schema_extra=_DEPRECATED_JSON_SCHEMA,
    )
    completion_model_kwargs: Optional[ModelKwargs] = Field(
        default=None,
        description=_DEPRECATED_DESCRIPTION,
        json_schema_extra=_DEPRECATED_JSON_SCHEMA,
    )


@partial_model
class AssistantUpdatePublic(AssistantCreatePublic):
    prompt: Optional[PromptCreate] = None
    attachments: Optional[list[ModelId]] = None
    groups: Optional[list[ModelId]] = None  # type: ignore[assignment]
    websites: Optional[list[ModelId]] = None  # type: ignore[assignment]
    integration_knowledge_list: Optional[list[ModelId]] = None  # type: ignore[assignment]
    mcp_servers: Optional[list[ModelId]] = None  # type: ignore[assignment]
    mcp_tools: Optional[list[MCPToolSetting]] = None
    description: Optional[str] = Field(  # type: ignore[assignment]  # NOT_PROVIDED sentinel default
        default=NOT_PROVIDED,
        description=(
            "A description of the assitant that will be used as "
            "default description in GroupChatAssistantPublic"
        ),
        json_schema_extra={"example": "This is a helpful AI assistant"},
    )
    insight_enabled: Optional[bool] = Field(
        default=None,
        description=(
            "Whether insights are enabled for this assistant. If enabled, users with "
            "appropriate permissions can see all sessions for this assistant."
        ),
    )
    data_retention_days: Optional[int] = None
    metadata_json: Union[dict[str, object], None, NotProvided] = Field(
        default=NOT_PROVIDED,
        description="Metadata for the assistant",
    )
    icon_id: Union[UUID, None, NotProvided] = Field(
        default=NOT_PROVIDED,
        description="Icon ID referencing an uploaded icon. Set to null to remove.",
    )


class AssistantCreate(AssistantBase):
    prompt: Optional[PromptCreate] = None
    space_id: UUID
    user_id: UUID
    groups: list[UUID] = Field(default_factory=_empty_uuid_list)
    websites: list[UUID] = Field(default_factory=_empty_uuid_list)
    guardrail_active: Optional[bool] = None
    completion_model_id: UUID = Field(
        validation_alias=AliasChoices(
            AliasPath("completion_model", "id"), "completion_model_id"
        )
    )


@partial_model
class AssistantUpdate(AssistantCreate):
    id: UUID


class AssistantPublicBase(InDB):
    name: str
    prompt: PromptCreate
    completion_model_kwargs: Optional[ModelKwargs] = None
    logging_enabled: bool | None
    space_id: Optional[UUID] = None


class AskAssistant(BaseModel):
    question: str
    session_id: Optional[UUID] = None  # Add optional session_id field
    files: list[UUID] = Field(default_factory=_empty_uuid_list)
    stream: bool = False
    tools: Optional[UseTools] = None


class AssistantResponse(BaseModel):
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    session: SessionInDB
    question: str
    question_id: Optional[UUID] = None
    files: list[File]
    answer: str | AsyncIterable[Completion]
    info_blobs: list[InfoBlobInDBWithScore]
    completion_model: CompletionModel | CompletionModelPublic
    tools: UseTools
    web_search_results: list[WebSearchResult]

    model_config = ConfigDict(arbitrary_types_allowed=True)
    description: Optional[str] = None


class AssistantSparse(ResourcePermissionsMixin, AssistantBase, InDB):
    user_id: UUID
    published: bool = False
    description: Optional[str] = None
    metadata_json: Optional[dict[str, object]] = Field(
        default=None,
        description="Metadata for the assistant",
    )
    type: AssistantType
    icon_id: Optional[UUID] = Field(
        default=None,
        description="Icon ID referencing an uploaded icon",
    )
    completion_model_id: Optional[UUID] = Field(
        default=None,
        description="ID of the completion model, or None if not configured",
    )


class AssistantPublic(InDB, ResourcePermissionsMixin):
    name: str
    prompt: Optional[PromptPublic] = None
    space_id: UUID
    completion_model_kwargs: ModelKwargs
    logging_enabled: bool | None
    attachments: list[FilePublic]
    allowed_attachments: FileRestrictions
    groups: list[CollectionPublic]
    websites: list[WebsitePublic]
    integration_knowledge_list: list[IntegrationKnowledgePublic]
    mcp_servers: list[MCPServerPublicDict] = Field(
        default_factory=_empty_mcp_server_public_dict_list
    )
    mcp_tools: list[MCPToolSetting] = Field(
        default_factory=_empty_mcp_tool_setting_list
    )  # Tool-level overrides
    completion_model: Optional[CompletionModelSparse] = None
    published: bool = False
    user: UserSparse
    tools: UseTools
    type: AssistantType
    model_info: Optional[ModelInfo] = None
    description: Optional[str] = Field(
        default=None,
        description=(
            "A description of the assitant that will be used "
            "as default description in GroupChatAssistantPublic"
        ),
        json_schema_extra={"example": "This is a helpful AI assistant"},
    )
    icon_id: Optional[UUID] = Field(
        default=None,
        description="Icon ID referencing an uploaded icon",
    )
    insight_enabled: bool = Field(
        description=(
            "Whether insights are enabled for this assistant. If enabled, users with "
            "appropriate permissions can see all sessions for this assistant."
        ),
    )
    data_retention_days: Optional[int] = Field(
        default=None,
        description="Number of days to retain data for this assistant",
    )
    metadata_json: Optional[dict[str, object]] = Field(
        default=None,
        description="Metadata for the assistant",
    )
    effective_config: Optional[EffectiveConfigPublic] = Field(
        default=None,
        description=(
            "Personal-assistant governance hints. Only populated for personal "
            "default assistants when a tenant policy applies."
        ),
    )
    is_help_assistant: bool = Field(
        default=False,
        description=(
            "True when this assistant currently fills a Help Assistant role "
            "(it has an active row in org_space_assistant_roles). Help "
            "assistants have logging permanently disabled; the edit UI uses "
            "this flag to surface that explanation. Only the single-assistant "
            "GET endpoint computes it; other responses default to False."
        ),
    )


class DefaultAssistant(AssistantPublic):
    completion_model: Optional[CompletionModelSparse] = None
    insight_enabled: bool = False


SessionInDB.model_rebuild()
