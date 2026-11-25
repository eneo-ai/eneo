# Copyright (c) 2025 Sundsvalls Kommun

from uuid import UUID

from eneo.storage.domain.storage import SpaceStorage
from eneo.storage.domain.storage_repo import StorageInfoRepository


class StorageInfoService:
    def __init__(self, repo: StorageInfoRepository) -> None:
        super().__init__()
        self.repo = repo

    async def get_storage_info(self):
        return await self.repo.get_storage_info()

    async def get_space_storage(self, space_id: UUID) -> SpaceStorage:
        """What one space stores. The caller's right to see it is the space's
        to decide (``SpaceService.require_space_admin``), not this service's."""
        return await self.repo.get_space_storage(space_id)
