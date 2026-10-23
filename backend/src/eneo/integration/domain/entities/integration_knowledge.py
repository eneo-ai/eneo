from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from eneo.base.base_entity import Entity

if TYPE_CHECKING:
    from eneo.embedding_models.domain.embedding_model import EmbeddingModel
    from eneo.integration.domain.entities.sharepoint_subscription import (
        SharePointSubscription,
    )
    from eneo.integration.domain.entities.user_integration import UserIntegration


_DEFAULT_SIZE = 0
_MAX_SYNC_ERROR_LENGTH = 1000

# A display name a person types or a SharePoint item name, as long as the
# names of assistant templates and uploaded files.
KNOWLEDGE_NAME_MAX_LENGTH = 255
KNOWLEDGE_NAME_LENGTH_REASON = (
    f"The name must be 1 to {KNOWLEDGE_NAME_MAX_LENGTH} characters long"
)

SYNC_STATUS_NEVER = "never"
SYNC_STATUS_SUCCESS = "success"
SYNC_STATUS_ERROR = "error"


class IntegrationKnowledge(Entity):
    def __init__(
        self,
        name: str,
        user_integration: "UserIntegration",
        embedding_model: "EmbeddingModel",
        tenant_id: UUID,
        space_id: UUID,
        id: Optional[UUID] = None,
        size: int | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        url: str | None = None,
        original_name: str | None = None,
        site_id: str | None = None,
        last_synced_at: datetime | None = None,
        last_sync_summary: dict[str, Any] | None = None,
        sharepoint_subscription_id: UUID | None = None,
        sharepoint_subscription: Optional["SharePointSubscription"] = None,
        delta_token: str | None = None,
        folder_id: str | None = None,
        folder_path: str | None = None,
        selected_item_type: str | None = None,
        resource_type: str | None = None,
        drive_id: str | None = None,
        wrapper_id: UUID | None = None,
        wrapper_name: str | None = None,
        last_sync_status: str | None = None,
        last_sync_error: str | None = None,
        last_sync_attempted_at: datetime | None = None,
        document_count: int | None = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.name = name
        self.original_name = original_name
        self.url = url
        self.tenant_id = tenant_id
        self.space_id = space_id
        self.user_integration = user_integration
        self.embedding_model = embedding_model
        self.size = size or _DEFAULT_SIZE
        self.site_id = site_id
        self.last_synced_at = last_synced_at
        self.last_sync_summary = last_sync_summary
        self.sharepoint_subscription_id = sharepoint_subscription_id
        self.sharepoint_subscription = sharepoint_subscription
        self.delta_token = delta_token
        self.folder_id = folder_id
        self.folder_path = folder_path
        self.selected_item_type = selected_item_type or "site_root"
        self.resource_type = resource_type or "site"
        self.drive_id = drive_id
        self.wrapper_id = wrapper_id
        self.wrapper_name = wrapper_name
        self.last_sync_status = last_sync_status or SYNC_STATUS_NEVER
        self.last_sync_error = last_sync_error
        self.last_sync_attempted_at = last_sync_attempted_at
        # Active documents indexed for this knowledge. Read-only projection
        # loaded by the repositories; never persisted.
        self.document_count = document_count or 0

    def mark_sync_started(self, at: datetime) -> None:
        self.last_sync_attempted_at = at

    def mark_sync_succeeded(self, at: datetime) -> None:
        self.last_sync_status = SYNC_STATUS_SUCCESS
        self.last_sync_error = None
        self.last_synced_at = at

    def mark_sync_failed(self, error: str) -> None:
        # last_sync_attempted_at is the start of the attempt (mark_sync_started);
        # a failure does not move it.
        self.last_sync_status = SYNC_STATUS_ERROR
        self.last_sync_error = error[:_MAX_SYNC_ERROR_LENGTH]

    @property
    def integration_type(self) -> str:
        return self.user_integration.tenant_integration.integration.integration_type
