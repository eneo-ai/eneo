from datetime import datetime
from typing import Optional
from uuid import UUID

from intric.base.base_entity import Entity


class SyncLog(Entity):
    """Domain entity for sync operation logs."""

    def __init__(
        self,
        integration_knowledge_id: UUID,
        sync_type: str,  # "full" or "delta"
        status: str,  # "success", "error", "in_progress"
        started_at: datetime,
        files_processed: int = 0,
        files_deleted: int = 0,
        pages_processed: int = 0,
        folders_processed: int = 0,
        skipped_items: int = 0,
        error_message: Optional[str] = None,
        metadata: Optional[dict] = None,
        completed_at: Optional[datetime] = None,
        id: Optional[UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.integration_knowledge_id = integration_knowledge_id
        self.sync_type = sync_type
        self.status = status
        self.error_message = error_message
        self.started_at = started_at
        self.completed_at = completed_at

        # Initialize metadata with count fields
        self.metadata = metadata or {}
        self.metadata.setdefault("files_processed", files_processed)
        self.metadata.setdefault("files_deleted", files_deleted)
        self.metadata.setdefault("pages_processed", pages_processed)
        self.metadata.setdefault("folders_processed", folders_processed)
        self.metadata.setdefault("skipped_items", skipped_items)

    @property
    def files_processed(self) -> int:
        """Get files_processed from metadata."""
        return self.metadata.get("files_processed", 0)

    @files_processed.setter
    def files_processed(self, value: int) -> None:
        """Set files_processed in metadata."""
        self.metadata["files_processed"] = value

    @property
    def files_deleted(self) -> int:
        """Get files_deleted from metadata."""
        return self.metadata.get("files_deleted", 0)

    @files_deleted.setter
    def files_deleted(self, value: int) -> None:
        """Set files_deleted in metadata."""
        self.metadata["files_deleted"] = value

    @property
    def pages_processed(self) -> int:
        """Get pages_processed from metadata."""
        return self.metadata.get("pages_processed", 0)

    @pages_processed.setter
    def pages_processed(self, value: int) -> None:
        """Set pages_processed in metadata."""
        self.metadata["pages_processed"] = value

    @property
    def folders_processed(self) -> int:
        """Get folders_processed from metadata."""
        return self.metadata.get("folders_processed", 0)

    @folders_processed.setter
    def folders_processed(self, value: int) -> None:
        """Set folders_processed in metadata."""
        self.metadata["folders_processed"] = value

    @property
    def skipped_items(self) -> int:
        """Get skipped_items from metadata."""
        return self.metadata.get("skipped_items", 0)

    @skipped_items.setter
    def skipped_items(self, value: int) -> None:
        """Set skipped_items in metadata."""
        self.metadata["skipped_items"] = value

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate sync duration in seconds."""
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def total_items_processed(self) -> int:
        """Total items processed in this sync."""
        return (
            self.files_processed
            + self.pages_processed
            + self.folders_processed
        )
