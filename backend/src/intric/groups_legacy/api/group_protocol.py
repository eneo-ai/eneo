from intric.groups_legacy.api.group_models import (
    DeleteGroupResponse,
    DeletionInfo,
    Group,
    GroupMetadata,
    GroupPublicWithMetadata,
)


def to_group_public_with_metadata(group: Group, num_info_blobs: int):
    return GroupPublicWithMetadata(
        **group.model_dump(exclude={"metadata"}),
        metadata=GroupMetadata(num_info_blobs=num_info_blobs, size=group.size),
    )


def to_groups_public_with_metadata(groups: list[Group], counts: list[int]):
    return [
        to_group_public_with_metadata(group, count)
        for group, count in zip(groups, counts)
    ]


def to_deletion_response(group: Group, num_info_blobs: int):
    return DeleteGroupResponse(
        **to_group_public_with_metadata(
            group, num_info_blobs=num_info_blobs
        ).model_dump(),
        deletion_info=DeletionInfo(success=True),
    )
