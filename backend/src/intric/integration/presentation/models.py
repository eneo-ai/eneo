from datetime import datetime
from enum import Enum
from typing import Dict, Generic, Literal, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, computed_field

from intric.ai_models.embedding_models.embedding_model import (
    EmbeddingModelPublicLegacy,
)
from intric.jobs.task_models import ResourceTaskParams
from intric.main.models import ResourcePermission

T = TypeVar("T", bound=BaseModel)


class BaseListModel(BaseModel, Generic[T]):
    items: list[T]

    @computed_field
    def count(self) -> int:
        return len(self.items)


class IntegrationType(str, Enum):
    Confluence = "confluence"
    Sharepoint = "sharepoint"

    @property
    def is_confluence(self) -> bool:
        return self == IntegrationType.Confluence

    @property
    def is_sharepoint(self) -> bool:
        return self == IntegrationType.Sharepoint


class Integration(BaseModel):
    id: UUID
    name: str
    description: str
    integration_type: IntegrationType


class IntegrationList(BaseListModel[Integration]):
    pass


class TenantIntegration(Integration):
    id: Optional[UUID] = None
    integration_id: UUID

    @computed_field
    def is_linked_to_tenant(self) -> bool:
        return self.id is not None


class TenantIntegrationList(BaseListModel[TenantIntegration]):
    pass


class TenantIntegrationFilter(Enum):
    DEFAULT = "all"
    TENANT_ONLY = "tenant_only"


class UserIntegration(Integration):
    id: Optional[UUID] = None
    tenant_integration_id: UUID
    connected: bool


class UserIntegrationList(BaseListModel[UserIntegration]):
    pass


class IntegrationCreate(BaseModel):
    name: str
    description: str
    integration_type: Literal["confluence", "sharepoint"]


class AuthUrlPublic(BaseModel):
    auth_url: str


class AuthCallbackParams(BaseModel):
    auth_code: str
    tenant_integration_id: UUID


class ConfluenceContentTaskParam(ResourceTaskParams):
    token_id: UUID
    space_key: str
    integration_knowledge_id: UUID


class SharepointContentTaskParam(ResourceTaskParams):
    token_id: UUID
    integration_knowledge_id: UUID
    site_id: str
    folder_id: Optional[str] = None
    folder_path: Optional[str] = None


class ConfluenceContentProcessParam(ResourceTaskParams):
    results: list


class IntegrationPreviewData(BaseModel):
    key: str
    type: str
    name: str
    url: str


class IntegrationPreviewDataList(BaseListModel[IntegrationPreviewData]):
    pass


class SharePointTreeItem(BaseModel):
    id: str
    name: str
    type: str
    path: str
    has_children: bool
    size: Optional[int] = None
    modified: Optional[datetime] = None
    web_url: Optional[str] = None


class SharePointTreeResponse(BaseModel):
    items: list[SharePointTreeItem]
    current_path: str
    parent_id: Optional[str] = None
    drive_id: str
    site_id: str


class IntegrationKnowledgeMetaData(BaseModel):
    size: int
    last_sync_summary: Optional[Dict[str, int]] = None
    last_synced_at: Optional[datetime] = None
    sharepoint_subscription_expires_at: Optional[datetime] = None


class IntegrationKnowledgePublic(BaseModel):
    id: UUID
    name: str
    url: str
    tenant_id: UUID
    space_id: UUID
    user_integration_id: UUID
    embedding_model: EmbeddingModelPublicLegacy
    site_id: Optional[str] = None
    sharepoint_subscription_id: Optional[str] = None
    sharepoint_subscription_expires_at: Optional[datetime] = None
    folder_id: Optional[str] = None
    folder_path: Optional[str] = None
    selected_item_type: Optional[str] = None
    permissions: list[ResourcePermission] = []
    metadata: IntegrationKnowledgeMetaData
    integration_type: Literal["confluence", "sharepoint"]
    task: Enum


class SyncLog(BaseModel):
    """Detailed sync operation log."""

    id: UUID
    integration_knowledge_id: UUID
    sync_type: str  # "full" or "delta"
    status: str  # "success", "error", "in_progress"
    metadata: Optional[dict] = None
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    created_at: datetime

    @computed_field
    def files_processed(self) -> int:
        """Get files_processed from metadata."""
        return (self.metadata or {}).get("files_processed", 0)

    @computed_field
    def files_deleted(self) -> int:
        """Get files_deleted from metadata."""
        return (self.metadata or {}).get("files_deleted", 0)

    @computed_field
    def pages_processed(self) -> int:
        """Get pages_processed from metadata."""
        return (self.metadata or {}).get("pages_processed", 0)

    @computed_field
    def folders_processed(self) -> int:
        """Get folders_processed from metadata."""
        return (self.metadata or {}).get("folders_processed", 0)

    @computed_field
    def skipped_items(self) -> int:
        """Get skipped_items from metadata."""
        return (self.metadata or {}).get("skipped_items", 0)

    @computed_field
    def duration_seconds(self) -> Optional[float]:
        """Calculate sync duration in seconds."""
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @computed_field
    def total_items_processed(self) -> int:
        """Total items processed in this sync."""
        return self.files_processed + self.pages_processed + self.folders_processed


class SyncLogList(BaseListModel[SyncLog]):
    pass


class PaginatedSyncLogList(BaseModel):
    """Paginated sync logs response with metadata."""

    items: list[SyncLog]
    total_count: int
    page_size: int
    offset: int

    @computed_field
    def count(self) -> int:
        return len(self.items)

    @computed_field
    def current_page(self) -> int:
        """Calculate the current page number (1-indexed)."""
        return (self.offset // self.page_size) + 1

    @computed_field
    def total_pages(self) -> int:
        """Calculate the total number of pages."""
        if self.total_count == 0:
            return 1
        return (self.total_count + self.page_size - 1) // self.page_size

    @computed_field
    def has_next(self) -> bool:
        """Check if there is a next page."""
        return (self.offset + self.page_size) < self.total_count

    @computed_field
    def has_previous(self) -> bool:
        """Check if there is a previous page."""
        return self.offset > 0
