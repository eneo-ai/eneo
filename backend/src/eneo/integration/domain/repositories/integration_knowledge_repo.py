from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from typing_extensions import TypedDict, Unpack

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )


@dataclass(frozen=True)
class IntegrationKnowledgeLocation:
    """Where an item's documents are in its source, read from columns only."""

    id: "UUID"
    integration_type: str
    url: str | None
    folder_path: str | None
    resource_type: str | None


class IntegrationKnowledgeSyncingError(Exception):
    """A change to an item waited too long for the row a running sync holds.

    A sync holds its row until it commits, which can take hours, so a rename
    or delete answers at once instead of holding the request open.
    """

    code = "integration_knowledge_syncing"

    def __init__(self) -> None:
        super().__init__("The source is syncing; try again when the sync has finished.")


class SyncStateFields(TypedDict, total=False):
    """The columns a sync pass owns; nothing a user edits (name, wrapper) is here."""

    site_id: str | None
    drive_id: str | None
    resource_type: str | None
    folder_id: str | None
    folder_path: str | None
    selected_item_type: str | None
    delta_token: str | None
    size: int
    last_sync_status: str
    last_sync_error: str | None
    last_sync_attempted_at: datetime | None
    last_synced_at: datetime | None
    last_sync_summary: dict[str, Any] | None
    sync_failed_items: dict[str, Any] | None


class IntegrationKnowledgeRepository(ABC):
    @abstractmethod
    async def one_or_none(
        self, id: "UUID | None" = None, **filters: object
    ) -> "IntegrationKnowledge | None": ...

    @abstractmethod
    async def one(
        self, id: "UUID | None" = None, **filters: object
    ) -> "IntegrationKnowledge": ...

    @abstractmethod
    async def add(self, obj: "IntegrationKnowledge") -> "IntegrationKnowledge": ...

    @abstractmethod
    async def get_by_ids(self, ids: list["UUID"]) -> list["IntegrationKnowledge"]: ...

    @abstractmethod
    async def get_location(self, id: "UUID") -> IntegrationKnowledgeLocation:
        """The item's location; raises NotFoundException when it is gone."""
        ...

    @abstractmethod
    async def attach_document_counts(
        self, items: "Sequence[IntegrationKnowledge]"
    ) -> None:
        """Set ``document_count`` (active info_blobs) on each item in one query.

        Fetches do not compute it; call this where an item is served to the UI.
        """
        ...

    @abstractmethod
    async def remove(self, id: "UUID") -> None:
        """Raises ``IntegrationKnowledgeSyncingError`` while a sync holds the row."""
        ...

    @abstractmethod
    async def update(self, obj: "IntegrationKnowledge") -> "IntegrationKnowledge": ...

    @abstractmethod
    async def rename(self, id: "UUID", name: str) -> None:
        """Write only ``name``, so a sync running meanwhile keeps its state.

        Raises ``IntegrationKnowledgeSyncingError`` while a sync holds the row.
        """
        ...

    @abstractmethod
    async def rename_wrapper(self, ids: "Sequence[UUID]", wrapper_name: str) -> None:
        """Write only ``wrapper_name`` on every item in ``ids``.

        Raises ``IntegrationKnowledgeSyncingError`` while a sync holds a row.
        """
        ...

    @abstractmethod
    async def link_subscription(self, id: "UUID", subscription_id: "UUID") -> bool:
        """Write only ``sharepoint_subscription_id``; False when it was not written.

        A row another transaction holds (a running sync, which links it
        itself) is skipped rather than waited for.
        """
        ...

    @abstractmethod
    async def update_sync_state(
        self, id: "UUID", **fields: Unpack[SyncStateFields]
    ) -> None:
        """Write only the given sync-owned columns.

        A sync holds its entity copy for minutes; ``update`` would write every
        column from that copy and undo a rename committed meanwhile.
        """
        ...

    @abstractmethod
    async def get_sync_failed_items(self, id: "UUID") -> dict[str, Any] | None:
        """The ``sync_failed_items`` column, which the entity does not carry."""
        ...

    @abstractmethod
    async def adjust_size(self, id: "UUID", delta: int) -> int:
        """Atomically add ``delta`` bytes (floored at zero) and return the new size.

        Several entity copies take part in one sync; a read-modify-write on any
        of them would overwrite the others' changes.
        """
        ...
