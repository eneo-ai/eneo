from enum import Enum
from typing import Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from intric.ai_models.completion_models.completion_model import (
    CompletionModelSparse,
    ModelKwargs,
)
from intric.ai_models.embedding_models.embedding_model import EmbeddingModelSparse
from intric.assistants.api.assistant_models import AssistantSparse, DefaultAssistant
from intric.collections.presentation.collection_models import CollectionPublic
from intric.completion_models.presentation.completion_model_models import (
    CompletionModelPublic,
)
from intric.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelPublic,
)
from intric.group_chat.presentation.models import GroupChatSparse
from intric.groups_legacy.api.group_models import GroupMetadata, GroupPublicWithMetadata
from intric.integration.presentation.models import IntegrationKnowledgePublic
from intric.main.models import (
    NOT_PROVIDED,
    InDB,
    ModelId,
    NotProvided,
    PaginatedPermissions,
    ResourcePermissionsMixin,
    partial_model,
)
from intric.security_classifications.presentation.security_classification_models import (
    SecurityClassificationPublic,
)
from intric.services.service import ServiceSparse
from intric.transcription_models.presentation.transcription_model_models import (
    TranscriptionModelPublic,
)
from intric.users.user import UserSparse
from intric.websites.crawl_dependencies.crawl_models import CrawlRunPublic
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import UpdateInterval
from intric.websites.presentation.website_models import WebsiteMetadata, WebsitePublic


class SpaceRoleValue(str, Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class CreateRequest(BaseModel):
    name: str


class TransferRequest(BaseModel):
    target_space_id: UUID


class TransferApplicationRequest(TransferRequest):
    move_resources: bool = False


# Members


class SpaceMember(UserSparse):
    role: SpaceRoleValue


# Apps


class AppSparse(ResourcePermissionsMixin, InDB):
    name: str
    description: Optional[str] = None
    published: bool
    user_id: UUID
    icon_id: Optional[UUID] = Field(
        default=None,
        description="Icon ID referencing an uploaded icon",
    )


# Spaces


class CreateSpaceRequest(CreateRequest):
    pass


@partial_model
class UpdateSpaceRequest(BaseModel):
    name: str
    description: str

    embedding_models: list[ModelId]
    completion_models: list[ModelId]
    transcription_models: list[ModelId]

    security_classification: Union[ModelId, NotProvided, None] = Field(
        default=NOT_PROVIDED,
        description=(
            "ID of the security classification to apply to this space. "
            "Set to null to remove the security classification. "
            "Omit to keep the current security classification unchanged."
        ),
    )
    icon_id: Union[UUID, None, NotProvided] = Field(
        default=NOT_PROVIDED,
        description="Icon ID referencing an uploaded icon. Set to null to remove.",
    )


class UpdateSpaceDryRunResponse(BaseModel):
    assistants: list[AssistantSparse]
    group_chats: list[GroupChatSparse]
    services: list[ServiceSparse]
    apps: list[AppSparse]
    completion_models: list[CompletionModelPublic]
    embedding_models: list[EmbeddingModelPublic]
    transcription_models: list[TranscriptionModelPublic]

    model_config = ConfigDict(from_attributes=True)


class Applications(BaseModel):
    assistants: PaginatedPermissions[AssistantSparse]
    group_chats: PaginatedPermissions[GroupChatSparse]
    services: PaginatedPermissions[ServiceSparse]
    apps: PaginatedPermissions[AppSparse]


class Knowledge(BaseModel):
    groups: PaginatedPermissions[CollectionPublic]
    websites: PaginatedPermissions[WebsitePublic]
    integration_knowledge_list: PaginatedPermissions[IntegrationKnowledgePublic]


class SpaceSparse(InDB, ResourcePermissionsMixin):
    name: str
    description: Optional[str]
    personal: bool
    organization: bool
    icon_id: Optional[UUID] = Field(
        default=None,
        description="Icon ID referencing an uploaded icon",
    ) 
    applications: Optional[Applications] = None
    default_assistant: Optional[DefaultAssistant] = None

class SpaceDashboard(SpaceSparse):
    applications: Applications


class SpaceRole(BaseModel):
    value: SpaceRoleValue

    @computed_field
    @property
    def label(self) -> str:
        return self.value.value.capitalize()


class SpacePublic(SpaceDashboard):
    embedding_models: list[EmbeddingModelPublic]
    completion_models: list[CompletionModelPublic]
    transcription_models: list[TranscriptionModelPublic]
    knowledge: Knowledge
    members: PaginatedPermissions[SpaceMember]

    default_assistant: DefaultAssistant 

    available_roles: list[SpaceRole]
    security_classification: Optional[SecurityClassificationPublic]


# Assistants


class WizardType(str, Enum):
    attachments = "attachments"
    groups = "groups"


class AdditionalField(BaseModel):
    type: WizardType
    value: list[dict[str, UUID]]


class TemplateCreate(BaseModel):
    id: UUID
    additional_fields: Optional[list[AdditionalField]]

    def get_ids_by_type(self, wizard_type: WizardType) -> list[UUID]:
        if self.additional_fields is None:
            return []

        return [
            item["id"]
            for field in self.additional_fields
            if field.type == wizard_type
            for item in field.value
        ]


class CreateSpaceAssistantRequest(CreateRequest):
    from_template: Optional[TemplateCreate] = None


class CreateSpaceAppRequest(CreateRequest):
    from_template: Optional[TemplateCreate] = None


class CreateSpaceServiceRequest(CreateRequest):
    pass


class CreateSpaceServiceResponse(InDB, ResourcePermissionsMixin):
    name: str
    prompt: str
    completion_model_kwargs: ModelKwargs
    output_format: Optional[Literal["json", "list", "boolean"]] = None
    json_schema: Optional[dict] = None

    groups: list[GroupPublicWithMetadata]
    completion_model: Optional[CompletionModelSparse]
    published: bool = False
    user: UserSparse


# Groups


class CreateSpaceGroupsRequest(CreateRequest):
    embedding_model: Optional[ModelId] = None


class CreateSpaceGroupsResponse(InDB):
    name: str
    embedding_model: Optional[EmbeddingModelSparse]
    metadata: GroupMetadata


# Websites


class CreateSpaceWebsitesRequest(BaseModel):
    name: Optional[str] = None
    url: str
    download_files: bool = False
    crawl_type: CrawlType = CrawlType.CRAWL
    update_interval: UpdateInterval = UpdateInterval.NEVER
    embedding_model: Optional[ModelId] = None


class CreateSpaceWebsitesResponse(InDB):
    name: Optional[str] = None
    url: str

    download_files: bool
    crawl_type: CrawlType
    update_interval: UpdateInterval

    embedding_model: Optional[EmbeddingModelSparse]
    latest_crawl: Optional[CrawlRunPublic]
    metadata: WebsiteMetadata


# Members


class AddSpaceMemberRequest(BaseModel):
    id: UUID
    role: SpaceRoleValue


class UpdateSpaceMemberRequest(BaseModel):
    role: SpaceRoleValue


class CreateSpaceIntegrationKnowledge(BaseModel):
    name: str
    embedding_model: ModelId
    url: str
    key: Optional[str] = None
