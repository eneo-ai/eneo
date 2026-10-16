from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, Literal, Optional, Self, TypeVar, cast
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from eneo.ai_models.embedding_models.embedding_model import (
    EmbeddingModelPublicLegacy,
)
from eneo.info_blobs.info_blob import SourceMetadataEntry
from eneo.integration.domain.value_objects import (
    IntegrationType,
    SkippedDetail,
    SyncMetadata,
)
from eneo.jobs.job_models import Task
from eneo.jobs.task_models import ResourceTaskParams
from eneo.main.models import ResourcePermission
from eneo.observability.error_text import user_visible_error

T = TypeVar("T", bound=BaseModel)


def _empty_resource_permissions() -> list[ResourcePermission]:
    return []


# What a sync wrote is cleaned again when served, so rows written before it
# described errors for users and named unplaced items by id never show URLs,
# SQL, host names or files from outside the imported item.
def _visible_error(value: Optional[str]) -> Optional[str]:
    return None if value is None else user_visible_error(value)


# Skips of delta items never placed in the item's scope: older syncs named
# their file, which may lie anywhere in the drive.
_UNPLACED_SKIP_REASONS = (
    "Folder scope path unavailable",
    "Missing item id",
    "Could not remove out-of-scope",
    "Could not remove removed:",
)


def _visible_skip(file: str, reason: str) -> SkippedDetail:
    reason = user_visible_error(reason)
    return SkippedDetail(
        file="" if reason.startswith(_UNPLACED_SKIP_REASONS) else file, reason=reason
    )


def _visible_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    # Summaries written by older syncs also hold the skipped files.
    cleaned = dict(summary)
    warning: object = cleaned.get("reconcile_warning")
    if isinstance(warning, str):
        cleaned["reconcile_warning"] = user_visible_error(warning)
    details: object = cleaned.get("skipped_details")
    if isinstance(details, list):
        cleaned["skipped_details"] = [
            _visible_detail(detail) for detail in cast(list[object], details)
        ]
    return cleaned


def _visible_detail(detail: object) -> object:
    if not isinstance(detail, dict):
        return detail
    entry = cast(Dict[str, object], detail)
    file, reason = entry.get("file"), entry.get("reason")
    if not isinstance(file, str) or not isinstance(reason, str):
        return entry
    return {**entry, **_visible_skip(file, reason)}


def _visible_sync_metadata(metadata: SyncMetadata) -> SyncMetadata:
    cleaned = metadata.copy()
    if "skipped_details" in cleaned:
        cleaned["skipped_details"] = [
            _visible_skip(detail["file"], detail["reason"])
            for detail in cleaned["skipped_details"]
        ]
    if "reconcile_warning" in cleaned:
        cleaned["reconcile_warning"] = user_visible_error(cleaned["reconcile_warning"])
    return cleaned


class BaseListModel(BaseModel, Generic[T]):
    items: list[T]

    @computed_field
    def count(self) -> int:
        return len(self.items)


class Integration(BaseModel):
    id: UUID
    name: str
    description: str
    integration_type: IntegrationType


class IntegrationList(BaseListModel[Integration]):
    pass


class TenantIntegration(Integration):
    id: UUID = Field(default_factory=uuid4)
    integration_id: UUID

    @computed_field
    def is_linked_to_tenant(self) -> bool:
        return True


class TenantIntegrationList(BaseListModel[TenantIntegration]):
    pass


class TenantIntegrationFilter(Enum):
    DEFAULT = "all"
    TENANT_ONLY = "tenant_only"


class UserIntegration(Integration):
    id: UUID = Field(default_factory=uuid4)
    tenant_integration_id: UUID
    connected: bool
    auth_type: str = "user_oauth"  # "user_oauth" or "tenant_app"
    tenant_app_id: Optional[UUID] = None
    tenant_app_configured: bool = True  # Whether tenant SharePoint app is configured


class UserIntegrationList(BaseListModel[UserIntegration]):
    pass


class IntegrationCreate(BaseModel):
    name: str
    description: str
    integration_type: Literal["confluence", "sharepoint"]


class AuthUrlPublic(BaseModel):
    auth_url: str
    state: str


class AuthCallbackParams(BaseModel):
    auth_code: str
    tenant_integration_id: UUID
    state: str


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
    results: list[dict[str, Any]]


class IntegrationPreviewData(BaseModel):
    key: str
    type: str
    name: str
    url: str
    category: Optional[str] = None


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
    # Library columns of a file, as they will be stored on import. Empty for
    # folders and for libraries whose columns cannot be read.
    source_metadata: list[SourceMetadataEntry] = []


class SharePointFilterColumn(BaseModel):
    """A library column a person can filter on without typing a value."""

    name: str
    label: str
    kind: Literal["choice", "boolean"]
    # The allowed values of a choice column; empty for yes/no columns.
    choices: list[str] = []


class SharePointTreeResponse(BaseModel):
    items: list[SharePointTreeItem]
    # True when the folder holds more items than ``items``; search to narrow.
    truncated: bool = False
    current_path: str
    parent_id: Optional[str] = None
    drive_id: str
    site_id: Optional[str] = None  # None for OneDrive
    # Filterable columns of the library behind the drive. Empty when the drive
    # has no backing list or its columns cannot be read.
    columns: list[SharePointFilterColumn] = []


class SharePointSearchResponse(BaseModel):
    """Files anywhere in a library that match a text and column filters."""

    items: list[SharePointTreeItem]
    # True when more files matched than ``items`` holds; narrow the search.
    truncated: bool = False
    drive_id: str
    site_id: Optional[str] = None


class IntegrationKnowledgeMetaData(BaseModel):
    size: int
    document_count: int = Field(
        0, description="Number of documents currently indexed for this knowledge"
    )
    last_sync_summary: Optional[Dict[str, Any]] = None
    last_synced_at: Optional[datetime] = Field(
        None, description="When the last successful sync completed"
    )
    last_sync_status: Literal["never", "success", "error"] = Field(
        "never", description="Outcome of the most recent sync attempt"
    )
    last_sync_error: Optional[str] = Field(
        None, description="Error message from the most recent failed sync"
    )
    last_sync_attempted_at: Optional[datetime] = Field(
        None, description="When the most recent sync attempt started"
    )
    sharepoint_subscription_expires_at: Optional[datetime] = Field(
        None,
        description="When the SharePoint webhook subscription expires (only for SharePoint integrations)",
    )

    @field_validator("last_sync_error")
    @classmethod
    def _user_visible_sync_error(cls, value: Optional[str]) -> Optional[str]:
        return _visible_error(value)

    @field_validator("last_sync_summary")
    @classmethod
    def _user_visible_sync_summary(
        cls, value: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        return None if value is None else _visible_summary(value)

    @property
    def subscription_status(self) -> Optional[str]:
        """Compute subscription status for SharePoint integrations.

        Returns:
            "active" | "expiring_soon" | "expired" | None
        """
        if not self.sharepoint_subscription_expires_at:
            return None

        from datetime import datetime, timedelta, timezone

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
    resource_type: Optional[str] = (
        None  # "site" for SharePoint, "onedrive" for OneDrive
    )
    sharepoint_subscription_id: Optional[UUID] = None
    folder_id: Optional[str] = None
    folder_path: Optional[str] = None
    selected_item_type: Optional[str] = None
    wrapper_id: Optional[UUID] = None
    wrapper_name: Optional[str] = None
    permissions: list[ResourcePermission] = Field(
        default_factory=_empty_resource_permissions
    )
    metadata: IntegrationKnowledgeMetaData
    integration_type: Literal["confluence", "sharepoint"]
    # Annotating the bare Enum base class produced an empty enum (`never`) in
    # the OpenAPI spec; the assembler always sets a Task member.
    task: Task


class SyncLog(BaseModel):
    """Detailed sync operation log."""

    id: UUID
    integration_knowledge_id: UUID
    sync_type: str  # "full" or "delta"
    status: str  # "success", "error", "in_progress"
    metadata: Optional[SyncMetadata] = None
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    created_at: datetime

    @field_validator("metadata")
    @classmethod
    def _user_visible_metadata(
        cls, value: Optional[SyncMetadata]
    ) -> Optional[SyncMetadata]:
        return None if value is None else _visible_sync_metadata(value)

    @field_validator("error_message")
    @classmethod
    def _user_visible_error_message(cls, value: Optional[str]) -> Optional[str]:
        return _visible_error(value)

    @computed_field
    def files_processed(self) -> int:
        """Get files_processed from metadata."""
        return int((self.metadata or {}).get("files_processed", 0))

    @computed_field
    def files_deleted(self) -> int:
        """Get files_deleted from metadata."""
        return int((self.metadata or {}).get("files_deleted", 0))

    @computed_field
    def pages_processed(self) -> int:
        """Get pages_processed from metadata."""
        return int((self.metadata or {}).get("pages_processed", 0))

    @computed_field
    def folders_processed(self) -> int:
        """Get folders_processed from metadata."""
        return int((self.metadata or {}).get("folders_processed", 0))

    @computed_field
    def skipped_items(self) -> int:
        """Get skipped_items from metadata."""
        return int((self.metadata or {}).get("skipped_items", 0))

    @computed_field
    def skipped_details(self) -> list[SkippedDetail]:
        """Get skipped file details from metadata."""
        return list((self.metadata or {}).get("skipped_details", []))

    @computed_field
    def duration_seconds(self) -> Optional[float]:
        """Calculate sync duration in seconds."""
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @computed_field
    def total_items_processed(self) -> int:
        """Total items processed in this sync."""
        return self.files_processed + self.pages_processed + self.folders_processed  # type: ignore[operator]


class SyncLogList(BaseListModel[SyncLog]):
    pass


class IntegrationDocumentItem(BaseModel):
    id: UUID
    title: str
    relative_path: str = Field(
        description="Folders between the imported item and the document, "
        "URL-decoded and without the file name; empty for the item itself."
    )
    url: Optional[str] = Field(None, description="Web URL of the source document")
    size: int
    updated_at: Optional[datetime] = None
    source_metadata: list[SourceMetadataEntry] = []


class IntegrationDocumentsPage(BaseModel):
    items: list[IntegrationDocumentItem]
    total_count: int = Field(description="Documents matching the query")
    limit: int
    offset: int
    total_size: int = Field(description="Summed size of the matching documents")


class IntegrationSkippedDocument(BaseModel):
    file: str
    reason: str

    @model_validator(mode="after")
    def _user_visible(self) -> Self:
        visible = _visible_skip(self.file, self.reason)
        self.file, self.reason = visible["file"], visible["reason"]
        return self


class IntegrationSkippedDocuments(BaseModel):
    """Files the latest sync of an item did not index."""

    items: list[IntegrationSkippedDocument]
    total: int = Field(description="Skipped files, including those not listed")
    truncated: bool = Field(description="True when the stored list was capped")
    synced_at: Optional[datetime] = Field(
        default=None,
        description="When the sync the list comes from finished or started",
    )


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
