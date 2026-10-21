from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
)

from eneo.ai_models.completion_models.completion_model import (
    CompletionModelPublic,
    CompletionModelSparse,
    ModelKwargs,
)
from eneo.ai_models.embedding_models.embedding_model import EmbeddingModelSparse
from eneo.assistants.api.assistant_models import (
    AssistantSparse,
    DefaultAssistant,
    MCPServerPublicDict,
)
from eneo.collections.presentation.collection_models import CollectionPublic
from eneo.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelPublic,
)
from eneo.group_chat.presentation.models import GroupChatSparse
from eneo.groups_legacy.api.group_models import GroupMetadata, GroupPublicWithMetadata
from eneo.integration.domain.entities.integration_knowledge import (
    KNOWLEDGE_NAME_MAX_LENGTH,
)
from eneo.integration.presentation.models import IntegrationKnowledgePublic
from eneo.integration.presentation.validation import (
    BATCH_ITEM_NAME_MAX_LENGTH,
    FOLDER_PATH_MAX_LENGTH,
    FOLDER_PATH_PATTERN,
    GRAPH_ID_MAX_LENGTH,
    GRAPH_ID_PATTERN,
    INTEGRATION_KEY_PATTERN,
    SELECTED_ITEM_TYPE_MAX_LENGTH,
    SELECTED_ITEM_TYPE_PATTERN,
    validate_folder_path,
    validate_https_url,
)
from eneo.jobs.job_models import JobPublic
from eneo.main.models import (
    NOT_PROVIDED,
    InDB,
    MCPToolSetting,
    ModelId,
    NotProvided,
    PaginatedPermissions,
    ResourcePermission,
    ResourcePermissionsMixin,
    partial_model,
)
from eneo.mcp_servers.domain.capabilities import (
    CapabilityAvailability,
    CapabilityPurpose,
)
from eneo.security_classifications.presentation.security_classification_models import (
    SecurityClassificationPublic,
)
from eneo.services.service import ServiceSparse
from eneo.transcription_models.presentation.transcription_model_models import (
    TranscriptionModelPublic,
)
from eneo.users.user import UserSparse
from eneo.websites.domain.crawl_run import CrawlType
from eneo.websites.domain.website import UpdateInterval
from eneo.websites.presentation.website_models import (
    CrawlRunPublic,
    WebsiteMetadata,
    WebsitePublic,
)


class SpaceRoleValue(str, Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class CreateRequest(BaseModel):
    name: str


class TransferRequest(BaseModel):
    target_space_id: UUID


def _empty_mcp_server_public_dict_list() -> list[MCPServerPublicDict]:
    return []


# Members


class SpaceMember(UserSparse):
    role: SpaceRoleValue


class SpaceGroupMember(InDB):
    name: str
    role: SpaceRoleValue
    user_count: int = 0


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
    enabled_capabilities: list[CapabilityPurpose]
    name: str
    description: str

    embedding_models: list[ModelId]
    completion_models: list[ModelId]
    transcription_models: list[ModelId]
    mcp_servers: list[ModelId]
    mcp_tools: list[MCPToolSetting]

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

    data_retention_days: Union[int, None, NotProvided] = Field(
        default=NOT_PROVIDED,
        ge=1,
        le=2555,
        description=(
            "Number of days to retain conversation history for this space. "
            "Applies to all assistants and apps in the space that don't have "
            "their own retention policy. Set to null to disable space-level retention. "
            "Omit to keep the current retention policy unchanged. "
            "Valid range: 1-2555 days (1 day to 7 years)."
        ),
    )


class UpdateSpaceDryRunResponse(BaseModel):
    capabilities: list[CapabilityPurpose] = Field(
        default_factory=list[CapabilityPurpose]
    )
    assistants: list[AssistantSparse]
    group_chats: list[GroupChatSparse]
    services: list[ServiceSparse]
    apps: list[AppSparse]
    completion_models: list[CompletionModelPublic]
    embedding_models: list[EmbeddingModelPublic]
    transcription_models: list[TranscriptionModelPublic]
    mcp_servers: list[MCPServerPublicDict] = Field(
        default_factory=_empty_mcp_server_public_dict_list
    )

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
    data_retention_days: Optional[int] = None


class SpaceDashboard(SpaceSparse):
    applications: Optional[Applications] = None


class SpaceRole(BaseModel):
    value: SpaceRoleValue

    @computed_field
    @property
    def label(self) -> str:
        return self.value.value.capitalize()


class SpacePublic(SpaceDashboard):
    organization_space_id: UUID | None = Field(
        description="Organization space identity, independent of the caller's membership."
    )
    enabled_capabilities: list[CapabilityPurpose] = Field(
        default_factory=list[CapabilityPurpose]
    )
    available_capabilities: list[CapabilityAvailability] = Field(
        default_factory=list[CapabilityAvailability]
    )
    embedding_models: list[EmbeddingModelPublic]
    completion_models: list[CompletionModelPublic]
    transcription_models: list[TranscriptionModelPublic]
    mcp_servers: list[MCPServerPublicDict] = Field(
        default_factory=_empty_mcp_server_public_dict_list
    )
    knowledge: Knowledge
    members: PaginatedPermissions[SpaceMember]
    group_members: PaginatedPermissions[SpaceGroupMember]
    skill_permissions: list[ResourcePermission]

    default_assistant: Optional[DefaultAssistant] = None

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
    enabled_capabilities: list[CapabilityPurpose] | None = None
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
    json_schema: Optional[dict[str, Any]] = None

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


# Group Members


class AddSpaceGroupMemberRequest(BaseModel):
    id: UUID
    role: SpaceRoleValue


class UpdateSpaceGroupMemberRequest(BaseModel):
    role: SpaceRoleValue


# Surrounding whitespace is dropped before the length is checked.
IntegrationKnowledgeName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=KNOWLEDGE_NAME_MAX_LENGTH
    ),
]


class _IntegrationKnowledgeSelection(BaseModel):
    """Where in SharePoint/OneDrive (or Confluence) a knowledge item points."""

    # Site id for SharePoint, drive id for OneDrive, space key for Confluence.
    key: Optional[str] = Field(
        None, max_length=GRAPH_ID_MAX_LENGTH, pattern=INTEGRATION_KEY_PATTERN
    )
    folder_id: Optional[str] = Field(
        None, max_length=GRAPH_ID_MAX_LENGTH, pattern=GRAPH_ID_PATTERN
    )
    folder_path: Optional[str] = Field(
        None, max_length=FOLDER_PATH_MAX_LENGTH, pattern=FOLDER_PATH_PATTERN
    )
    selected_item_type: Optional[str] = Field(
        None,
        max_length=SELECTED_ITEM_TYPE_MAX_LENGTH,
        pattern=SELECTED_ITEM_TYPE_PATTERN,
    )
    resource_type: Optional[Literal["site", "onedrive"]] = "site"

    @field_validator("folder_path")
    @classmethod
    def _folder_path_without_traversal(cls, value: Optional[str]) -> Optional[str]:
        return validate_folder_path(value)


class CreateSpaceIntegrationKnowledge(_IntegrationKnowledgeSelection):
    name: IntegrationKnowledgeName
    embedding_model: ModelId
    url: str

    @field_validator("url")
    @classmethod
    def _https_url(cls, value: str) -> str:
        return validate_https_url(value)


class CreateSpaceIntegrationKnowledgeBatchItem(_IntegrationKnowledgeSelection):
    name: str = Field(
        max_length=BATCH_ITEM_NAME_MAX_LENGTH,
        description=f"Stored without surrounding whitespace; an item whose name "
        f"is then empty or longer than {KNOWLEDGE_NAME_MAX_LENGTH} characters "
        "fails on its own",
    )
    url: str

    @field_validator("url")
    @classmethod
    def _https_url(cls, value: str) -> str:
        return validate_https_url(value)


class CreateSpaceIntegrationKnowledgeBatchRequest(BaseModel):
    embedding_model: ModelId
    # Blank means no wrapper name.
    wrapper_name: Optional[str] = Field(None, max_length=KNOWLEDGE_NAME_MAX_LENGTH)
    items: list[CreateSpaceIntegrationKnowledgeBatchItem] = Field(
        min_length=1, max_length=50
    )


class CreateSpaceIntegrationKnowledgeBatchResult(BaseModel):
    index: int
    name: str
    status: Literal["created", "failed"]
    integration_knowledge_id: Optional[UUID] = None
    job: Optional[JobPublic] = None
    error: Optional[str] = None


class CreateSpaceIntegrationKnowledgeBatchResponse(BaseModel):
    items: list[CreateSpaceIntegrationKnowledgeBatchResult]
    created_count: int
    failed_count: int


class UpdateIntegrationKnowledgeRequest(BaseModel):
    name: IntegrationKnowledgeName


class UpdateIntegrationKnowledgeWrapperRequest(BaseModel):
    name: IntegrationKnowledgeName
