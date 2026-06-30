# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from eneo.storage.domain.storage_repo import StorageInfoRepository


class StorageInfoService:
    def __init__(self, repo: StorageInfoRepository) -> None:
        super().__init__()
        self.repo = repo

    async def get_storage_info(self):
        return await self.repo.get_storage_info()
