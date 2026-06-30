# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.


from eneo.spaces.api.space_models import SpaceMember
from eneo.storage.domain.storage import StorageInfo, StorageSpaceInfo
from eneo.storage.presentation.storage_models import (
    StorageInfoModel,
    StorageModel,
    StorageSpaceInfoModel,
    StorageSpaceMemberModel,
)


class StorageInfoAssembler:
    def from_space_member_to_storage_space_member(
        self,
        space_member: SpaceMember,
    ) -> StorageSpaceMemberModel:
        return StorageSpaceMemberModel(
            created_at=space_member.created_at,
            updated_at=space_member.updated_at,
            id=space_member.id,
            email=space_member.email,
            role=space_member.role,
        )

    def from_storage_space_info_to_model(
        self, space: StorageSpaceInfo
    ) -> StorageSpaceInfoModel:
        space_members = [
            self.from_space_member_to_storage_space_member(space_member=space_member)
            for space_member in space.members
        ]

        return StorageSpaceInfoModel(
            created_at=space.created_at,
            update_at=space.updated_at,
            id=space.space_id,
            name=space.name,
            size=space.size,
            members=space_members,
        )

    def from_storage_info_to_model(self, storage: StorageInfo) -> StorageInfoModel:
        count = len(storage.get_shared_spaces())
        storage_space_infos = [
            self.from_storage_space_info_to_model(space=space)
            for space in storage.get_shared_spaces().values()
        ]

        return StorageInfoModel(count=count, items=storage_space_infos)

    def from_storage_to_model(self, storage: StorageInfo):
        return StorageModel(
            total_used=storage.total_used,
            personal_used=storage.personal_used,
            shared_used=storage.shared_used,
            limit=storage.get_quota_limit(),
        )
