# Copyright (c) 2025 Sundsvalls Kommun


from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from eneo.spaces.api.space_models import SpaceMember


@dataclass(frozen=True)
class SpaceStorage:
    """What one space stores, by kind of knowledge. A number to read, not a
    limit: nothing is refused because of it."""

    collections_size: int
    websites_size: int
    integration_knowledge_size: int

    @property
    def size(self) -> int:
        return (
            self.collections_size + self.websites_size + self.integration_knowledge_size
        )


class StorageSpaceInfo:
    """
    Represents storage information for a specific space.
    This class is used internally by StorageInfo to track storage usage per space.
    """

    def __init__(
        self,
        space_id: "UUID",
        created_at: "datetime",
        updated_at: "datetime",
        name: str,
        size: int,
        members: list["SpaceMember"],
        user_id: Optional["UUID"],
    ) -> None:
        super().__init__()
        self.space_id = space_id
        self.created_at = created_at
        self.updated_at = updated_at
        self.name = name
        self.size = size
        self.members = members
        self.user_id = user_id


class StorageInfo:
    """Contains storage information regarding spaces and quota limits"""

    def __init__(
        self,
        shared_spaces: dict["UUID", StorageSpaceInfo],
        personal_spaces: dict["UUID", StorageSpaceInfo],
        quota_limit: int,
    ) -> None:
        super().__init__()
        self._shared_spaces = shared_spaces
        self._personal_spaces = personal_spaces
        self._quota_limit = quota_limit

    @property
    def personal_used(self) -> int:
        return sum(space.size for space in self._personal_spaces.values())

    @property
    def shared_used(self) -> int:
        return sum(space.size for space in self._shared_spaces.values())

    @property
    def total_used(self) -> int:
        # NOTE: could also do in db.
        return self.personal_used + self.shared_used

    def get_quota_limit(self) -> int:
        return self._quota_limit

    def get_shared_spaces(self) -> dict["UUID", StorageSpaceInfo]:
        return self._shared_spaces.copy()
