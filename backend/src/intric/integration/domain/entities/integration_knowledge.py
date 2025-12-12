from datetime import datetime
from typing import TYPE_CHECKING, Optional, Dict
from uuid import UUID

from intric.base.base_entity import Entity

if TYPE_CHECKING:
    from intric.embedding_models.domain.embedding_model import EmbeddingModel
    from intric.integration.domain.entities.user_integration import UserIntegration
    from intric.integration.domain.entities.sharepoint_subscription import SharePointSubscription


_DEFAULT_SIZE = 0


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
        last_sync_summary: Dict[str, int] | None = None,
        sharepoint_subscription_id: UUID | None = None,
        sharepoint_subscription: Optional["SharePointSubscription"] = None,
        delta_token: str | None = None,
        folder_id: str | None = None,
        folder_path: str | None = None,
        selected_item_type: str | None = None,
        resource_type: str | None = None,
        drive_id: str | None = None,
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

    @property
    def integration_type(self) -> str:
        return self.user_integration.tenant_integration.integration.integration_type
