# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import TYPE_CHECKING, cast
from uuid import UUID

from typing_extensions import TypedDict

from eneo.spaces.api.space_models import SpaceMember, SpaceRoleValue
from eneo.storage.domain.storage import StorageInfo, StorageSpaceInfo

if TYPE_CHECKING:
    from eneo.database.tables.spaces_table import Spaces


class StorageInfoQueryResult(TypedDict):
    spaces: "Spaces"
    group_size: int
    website_size: int
    integration_knowledge_size: int
    total_size: int
    quota_limit: int


class StorageInfoFactory:
    @staticmethod
    def _create_storage_space_info_from_db(
        query_result: list[StorageInfoQueryResult],
    ) -> dict[UUID, StorageSpaceInfo]:
        storage_space_info_dict: dict[UUID, StorageSpaceInfo] = {}
        for row in query_result:
            space = row["spaces"]
            space_name = space.name
            space_id = space.id
            created_at = space.created_at
            updated_at = space.updated_at
            user_id = space.user_id
            total_size = row["total_size"]

            space_members = [
                SpaceMember.model_validate(
                    {
                        # to_dict() from SerializeMixin is untyped; cast to dict[str, object]
                        **cast(dict[str, object], space_user.user.to_dict()),  # pyright: ignore[reportUnknownMemberType]  # SerializeMixin.to_dict has no stubs
                        "role": SpaceRoleValue(space_user.role),
                    }
                )
                for space_user in space.members
                if space_user.user.deleted_at is None
            ]
            storage_space_info = StorageSpaceInfo(
                space_id=space_id,
                created_at=created_at,
                updated_at=updated_at,
                name=space_name,
                size=total_size,
                members=space_members,
                user_id=user_id,
            )

            storage_space_info_dict[space_id] = storage_space_info

        return storage_space_info_dict

    @staticmethod
    def create_storage_info_from_db(
        query_result: list[StorageInfoQueryResult],
    ) -> StorageInfo:
        quota_limit = query_result[0]["quota_limit"]
        space_info_dict = StorageInfoFactory._create_storage_space_info_from_db(
            query_result=query_result
        )
        personal_spaces_dict: dict[UUID, StorageSpaceInfo] = {}
        shared_spaces_dict: dict[UUID, StorageSpaceInfo] = {}

        for space_id, space in space_info_dict.items():
            if space.user_id is not None:
                personal_spaces_dict[space_id] = space
            else:
                shared_spaces_dict[space_id] = space

        storage_info = StorageInfo(
            shared_spaces=shared_spaces_dict,
            personal_spaces=personal_spaces_dict,
            quota_limit=quota_limit,
        )

        return storage_info
