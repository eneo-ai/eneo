from datetime import datetime
from enum import Enum
from typing import Dict, Generic, Literal, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field, computed_field

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
    auth_type: str = "user_oauth"  # "user_oauth" or "tenant_app"
    tenant_app_id: Optional[UUID] = None


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
    token_id: Optional[UUID] = None  # For user_oauth integrations
    tenant_app_id: Optional[UUID] = None  # For tenant_app integrations
    integration_knowledge_id: UUID
    site_id: Optional[str] = None  # Required for SharePoint, None for OneDrive
    drive_id: Optional[str] = None  # Required for OneDrive, optional for SharePoint
    folder_id: Optional[str] = None
    folder_path: Optional[str] = None
    resource_type: str = "site"  # "site" for SharePoint, "onedrive" for OneDrive


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
    site_id: Optional[str] = None  # None for OneDrive


class IntegrationKnowledgeMetaData(BaseModel):
    size: int
    last_sync_summary: Optional[Dict[str, int]] = None
    last_synced_at: Optional[datetime] = None
    sharepoint_subscription_expires_at: Optional[datetime] = Field(
        None,
        description="When the SharePoint webhook subscription expires (only for SharePoint integrations)"
    )

    @property
    def subscription_status(self) -> Optional[str]:
        """Compute subscription status for SharePoint integrations.

        Returns:
            "active" | "expiring_soon" | "expired" | None
        """
        if not self.sharepoint_subscription_expires_at:
            return None

        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        expires_at = self.sharepoint_subscription_expires_at

        if expires_at <= now:
            return "expired"
        elif expires_at <= now + timedelta(hours=48):
            return "expiring_soon"
        else:
            return "active"

    @property
    def subscription_expires_in_hours(self) -> Optional[int]:
        """Hours until subscription expires.

        Returns:
            Number of hours (0 if expired), or None if no subscription
        """
        if not self.sharepoint_subscription_expires_at:
            return None

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        delta = self.sharepoint_subscription_expires_at - now
        return max(0, int(delta.total_seconds() / 3600))


class IntegrationKnowledgePublic(BaseModel):
    id: UUID
    name: str
    original_name: Optional[str] = None
    url: str
    tenant_id: UUID
    space_id: UUID
    user_integration_id: UUID
    embedding_model: EmbeddingModelPublicLegacy
    site_id: Optional[str] = None
    drive_id: Optional[str] = None  # For OneDrive direct access
    resource_type: Optional[str] = None  # "site" for SharePoint, "onedrive" for OneDrive
    sharepoint_subscription_id: Optional[UUID] = None
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
