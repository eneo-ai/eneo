from collections.abc import Mapping
from datetime import datetime
from typing import (
    Any,
    Dict,
    Generic,
    Literal,
    Optional,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    Field,
    TypeAdapter,
    ValidationError,
    computed_field,
    field_validator,
    model_validator,
)

from eneo.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelPublic,
)
from eneo.info_blobs.info_blob import SourceMetadataEntry
from eneo.integration.domain.entities.sync_log import SyncLog as SyncLogEntity
from eneo.integration.domain.skip_reasons import SkipReasonCode, visible_skip
from eneo.integration.domain.sync_progress import IntegrationSyncProgress

# Re-exported: jobs queued before the task parameters moved to the domain are
# pickled under this module's name.
from eneo.integration.domain.task_params import (
    ConfluenceContentTaskParam as ConfluenceContentTaskParam,
)
from eneo.integration.domain.task_params import (
    SharepointContentTaskParam as SharepointContentTaskParam,
)
from eneo.integration.domain.value_objects import (
    IntegrationType,
    SkippedDetail,
    SyncMetadata,
)
from eneo.integration.presentation.validation import https_url_or_none
from eneo.jobs.job_models import Task
from eneo.main.models import ResourcePermission
from eneo.observability.error_text import user_visible_error

T = TypeVar("T", bound=BaseModel)

# Above this an offset stops being a page anyone browses to, and past int64
# the database driver fails the query.
MAX_PAGE_OFFSET = 1_000_000


def _empty_resource_permissions() -> list[ResourcePermission]:
    return []


# What a sync wrote is cleaned again when served, so rows written before it
# described errors for users and named unplaced items by id never show URLs,
# SQL, host names or files from outside the imported item.
def _visible_error(value: Optional[str]) -> Optional[str]:
    return None if value is None else user_visible_error(value)


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
    # A sync names an item Graph returned without a name as a null file; a
    # detail without a readable reason keeps its shape and loses the reason.
    return {**entry, **visible_skip(entry)}


_SYNC_METADATA_HINTS = get_type_hints(SyncMetadata)
_SYNC_METADATA_TYPES = {
    key: TypeAdapter(hint)
    for key, hint in _SYNC_METADATA_HINTS.items()
    if get_origin(hint) is not list
}
# List keys are read entry by entry, so one odd entry loses only itself.
_SYNC_METADATA_ENTRY_TYPES = {
    key: TypeAdapter(get_args(hint)[0])
    for key, hint in _SYNC_METADATA_HINTS.items()
    if get_origin(hint) is list
}


def served_sync_metadata(metadata: object) -> Dict[str, Any]:
    """A stored sync log's metadata as served: cleaned, and only the values
    that have their declared type.

    A row another release wrote, with a null, an unknown key or a changed
    type, loses that value (or that list entry) instead of failing the
    whole response.
    """
    if not isinstance(metadata, dict):
        return {}
    readable: Dict[str, Any] = {}
    for key, value in _visible_summary(cast(Dict[str, Any], metadata)).items():
        if key in _SYNC_METADATA_ENTRY_TYPES:
            if isinstance(value, list):
                entry_type = _SYNC_METADATA_ENTRY_TYPES[key]
                readable[key] = [
                    entry
                    for entry in cast(list[object], value)
                    if _validates(entry_type, entry)
                ]
        elif key in _SYNC_METADATA_TYPES and value is not None:
            if _validates(_SYNC_METADATA_TYPES[key], value):
                readable[key] = value
    return readable


def _validates(adapter: TypeAdapter[Any], value: object) -> bool:
    try:
        adapter.validate_python(value)
    except ValidationError:
        return False
    return True


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
    # The issued state is token_urlsafe(32), 43 characters.
    state: str = Field(max_length=256)


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
    url: Optional[str] = Field(
        description="Web URL of the item in its source; null unless an absolute "
        "https URL"
    )
    tenant_id: UUID
    space_id: UUID
    user_integration_id: UUID
    embedding_model: EmbeddingModelPublic
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

    @field_validator("url")
    @classmethod
    def _https_only(cls, value: Optional[str]) -> Optional[str]:
        return https_url_or_none(value)


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

    @classmethod
    def from_domain(cls, log: SyncLogEntity) -> "SyncLog":
        return cls(
            id=log.id,
            integration_knowledge_id=log.integration_knowledge_id,
            sync_type=log.sync_type,
            status=log.status,
            metadata=log.metadata,
            error_message=log.error_message,
            started_at=log.started_at,
            completed_at=log.completed_at,
            created_at=log.created_at or log.started_at,
        )

    # Cleaned before validation: a stored detail with a null file would not
    # pass the SkippedDetail shape otherwise.
    @field_validator("metadata", mode="before")
    @classmethod
    def _user_visible_metadata(cls, value: object) -> object:
        if isinstance(value, dict):
            return served_sync_metadata(cast(object, value))
        return value

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
    url: Optional[str] = Field(
        None,
        description="Web URL of the source document; null unless an absolute https URL",
    )
    size: int
    updated_at: Optional[datetime] = None
    source_metadata: list[SourceMetadataEntry] = []

    @field_validator("url")
    @classmethod
    def _https_only(cls, value: Optional[str]) -> Optional[str]:
        return https_url_or_none(value)


class IntegrationDocumentsPage(BaseModel):
    items: list[IntegrationDocumentItem]
    total_count: int = Field(description="Documents matching the query")
    limit: int
    offset: int
    total_size: int = Field(description="Summed size of the matching documents")


class IntegrationSkippedDocument(BaseModel):
    file: str
    reason: str = Field(description="The reason as text, for logs and older clients")
    code: SkipReasonCode = Field(description="Why the file was skipped")
    params: dict[str, str | int] = Field(
        default_factory=dict,
        description="What the code refers to: a file type, a limit, an HTTP status",
    )
    retry: bool = Field(
        default=False,
        description="The pass could not finish the file; the next sync tries again",
    )

    # Rows written before codes existed are classified from their text here.
    @model_validator(mode="before")
    @classmethod
    def _user_visible(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        entry = cast(Mapping[str, Any], value)
        return {**entry, **visible_skip(entry)}


class IntegrationSkippedDocuments(BaseModel):
    """Files the latest sync of an item did not index."""

    items: list[IntegrationSkippedDocument]
    total: int = Field(description="Skipped files, including those not listed")
    truncated: bool = Field(description="True when the stored list was capped")
    synced_at: Optional[datetime] = Field(
        default=None,
        description="When the sync the list comes from finished or started",
    )


class IntegrationSyncProgressList(BaseModel):
    """Running syncs of a space's integration knowledge; idle items are absent."""

    items: list[IntegrationSyncProgress]


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


class IntegrationSyncWindowRequest(BaseModel):
    integration_knowledge_id: UUID
    offset: int = Field(default=0, ge=0, le=MAX_PAGE_OFFSET)


class IntegrationSyncDetailsRequest(BaseModel):
    items: list[IntegrationSyncWindowRequest] = Field(min_length=1, max_length=50)
    limit: int = Field(default=10, ge=1, le=10)

    @model_validator(mode="after")
    def unique_items(self) -> "IntegrationSyncDetailsRequest":
        if len({item.integration_knowledge_id for item in self.items}) != len(
            self.items
        ):
            raise ValueError("Each integration knowledge item may appear only once")
        return self


class IntegrationSyncDetails(BaseModel):
    integration_knowledge_id: UUID
    history: PaginatedSyncLogList
    skipped: IntegrationSkippedDocuments | None = Field(
        description="Latest skipped files on the first page; null on older history pages"
    )


class IntegrationSyncDetailsList(BaseModel):
    items: list[IntegrationSyncDetails]
