from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import AsyncIterable, Optional
from uuid import UUID

from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from intric.ai_models.completion_models.completion_model import (
    CompletionModel,
    CompletionModelSparse,
    ModelKwargs,
)
from intric.ai_models.embedding_models.embedding_model import EmbeddingModelLegacy
from intric.collections.presentation.collection_models import CollectionPublic
from intric.completion_models.infrastructure.web_search import WebSearchResult
from intric.files.file_models import File, FilePublic, FileRestrictions
from intric.groups_legacy.api.group_models import GroupInDBBase
from intric.info_blobs.info_blob import InfoBlobInDBNoText
from intric.integration.presentation.models import IntegrationKnowledgePublic
from intric.main.config import get_settings
from intric.main.models import (
    NOT_PROVIDED,
    InDB,
    ModelId,
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
    token_limit: int
    prompt_tokens: Optional[int] = None


# Relationship models
class GroupWithEmbeddingModel(GroupInDBBase):
    embedding_model: Optional[EmbeddingModelLegacy] = None


# Models
class AssistantGuard(BaseModel):
    guardrail_active: bool = True
    guardrail_string: str = ""
    on_fail_message: str = "Jag kan tyvärr inte svara på det. Fråga gärna något annat!"


class AssistantBase(BaseModel):
    name: str
    completion_model_kwargs: ModelKwargs = ModelKwargs()
    logging_enabled: bool = False

    @field_validator("completion_model_kwargs", mode="before")
    @classmethod
    def set_model_kwargs(cls, model_kwargs):
        return model_kwargs or ModelKwargs()


class AssistantCreatePublic(AssistantBase):
    space_id: UUID
    prompt: Optional[PromptCreate] = Field(
        default=None, deprecated=True, description="This field is deprecated and will be ignored"
    )
    groups: list[ModelId] = Field(
        default=[], deprecated=True, description="This field is deprecated and will be ignored"
    )
    websites: list[ModelId] = Field(
        default=[], deprecated=True, description="This field is deprecated and will be ignored"
    )
    integration_knowledge_list: list[ModelId] = Field(
        default=[], deprecated=True, description="This field is deprecated and will be ignored"
    )
    guardrail: Optional[AssistantGuard] = Field(
        default=None, deprecated=True, description="This field is deprecated and will be ignored"
    )
    completion_model: Optional[ModelId] = Field(
        default=None,
        deprecated=True,
        description="This field is deprecated and will be ignored",
    )
    logging_enabled: Optional[bool] = Field(
        default=None, deprecated=True, description="This field is deprecated and will be ignored"
    )
    completion_model_kwargs: Optional[ModelKwargs] = Field(
        default=None, deprecated=True, description="This field is deprecated and will be ignored"
    )


@partial_model
class AssistantUpdatePublic(AssistantCreatePublic):
    prompt: Optional[PromptCreate] = None
    attachments: Optional[list[ModelId]] = None
    description: Optional[str] = Field(
        default=NOT_PROVIDED,
        description=(
            "A description of the assitant that will be used as "
            "default description in GroupChatAssistantPublic"
        ),
        example="This is a helpful AI assistant",
    )
    insight_enabled: Optional[bool] = Field(
        default=None,
        description=(
            "Whether insights are enabled for this assistant. If enabled, users with "
            "appropriate permissions can see all sessions for this assistant."
        ),
    )
    data_retention_days: Optional[int] = None
    metadata_json: Optional[dict] = Field(
        default=NOT_PROVIDED,
        description="Metadata for the assistant",
    )


class AssistantCreate(AssistantBase):
    prompt: Optional[PromptCreate] = None
    space_id: UUID
    user_id: UUID
    groups: list[ModelId] = []
    websites: list[ModelId] = []
    guardrail_active: Optional[bool] = None
    completion_model_id: UUID = Field(
        validation_alias=AliasChoices(AliasPath("completion_model", "id"), "completion_model_id")
    )


@partial_model
class AssistantUpdate(AssistantCreate):
    id: UUID


class AssistantPublicBase(InDB):
    name: str
    prompt: PromptCreate
    completion_model_kwargs: Optional[ModelKwargs] = None
    logging_enabled: bool
    space_id: Optional[UUID] = None


class AskAssistant(BaseModel):
    question: str
    session_id: Optional[UUID] = None  # Add optional session_id field
    files: list[ModelId] = Field(max_length=get_settings().max_in_question, default=[])
    stream: bool = False
    tools: Optional[UseTools] = None


class AssistantResponse(BaseModel):
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    session: SessionInDB
    question: str
    question_id: Optional[UUID] = None
    files: list[File]
    answer: str | AsyncIterable[str]
    info_blobs: list[InfoBlobInDBNoText]
    completion_model: CompletionModel
    tools: UseTools
    web_search_results: list[WebSearchResult]

    model_config = ConfigDict(arbitrary_types_allowed=True)
    description: Optional[str] = None


class AssistantSparse(ResourcePermissionsMixin, AssistantBase, InDB):
    user_id: UUID
    published: bool = False
    description: Optional[str] = None
    metadata_json: Optional[dict] = Field(
        default=None,
        description="Metadata for the assistant",
    )
    type: AssistantType


class AssistantPublic(InDB, ResourcePermissionsMixin):
    name: str
    prompt: Optional[PromptPublic] = None
    space_id: UUID
    completion_model_kwargs: ModelKwargs
    logging_enabled: bool
    attachments: list[FilePublic]
    allowed_attachments: FileRestrictions
    groups: list[CollectionPublic]
    websites: list[WebsitePublic]
    integration_knowledge_list: list[IntegrationKnowledgePublic]
    completion_model: CompletionModelSparse
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
        example="This is a helpful AI assistant",
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
    metadata_json: Optional[dict] = Field(
        default=None,
        description="Metadata for the assistant",
    )


class DefaultAssistant(AssistantPublic):
    completion_model: Optional[CompletionModelSparse] = None
    insight_enabled: bool = False


SessionInDB.model_rebuild()
