from datetime import datetime
from typing import TYPE_CHECKING, Dict, Optional
from uuid import UUID

from eneo.base.base_entity import Entity
from eneo.embedding_models.domain.chunking import resolve_source_chunk_config
from eneo.main.models import NOT_PROVIDED, NotProvided, is_provided

if TYPE_CHECKING:
    from eneo.embedding_models.domain.embedding_model import EmbeddingModel
    from eneo.integration.domain.entities.sharepoint_subscription import (
        SharePointSubscription,
    )
    from eneo.integration.domain.entities.user_integration import UserIntegration


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
        wrapper_id: UUID | None = None,
        wrapper_name: str | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
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
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def update(
        self,
        name: str | NotProvided = NOT_PROVIDED,
        chunk_size: int | None | NotProvided = NOT_PROVIDED,
        chunk_overlap: int | None | NotProvided = NOT_PROVIDED,
    ) -> None:
        """Apply a partial update, mirroring Collection.update and Website.update.

        The sentinel matters more here than elsewhere: this is also the rename path,
        so treating an omitted field as ``None`` would silently return the source to
        the platform default. For an integration that means the next sync sees drifted
        stamps and re-syncs the whole corpus — a rename would quietly cost a full
        re-index.
        """
        if is_provided(name):
            self.name = name
        if is_provided(chunk_size) or is_provided(chunk_overlap):
            # Merge with what is stored: the two fields are one setting, so a size-only
            # change still has to be valid next to the retained overlap.
            self.chunk_size, self.chunk_overlap = resolve_source_chunk_config(
                chunk_size=chunk_size if is_provided(chunk_size) else self.chunk_size,
                chunk_overlap=(
                    chunk_overlap if is_provided(chunk_overlap) else self.chunk_overlap
                ),
                max_input=self.embedding_model.max_input,
            )

    @property
    def integration_type(self) -> str:
        return self.user_integration.tenant_integration.integration.integration_type
