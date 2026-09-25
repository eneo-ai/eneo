# MIT License

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses, to_paginated_response
from eneo.user_groups.user_group import (
    UserGroupCreateRequest,
    UserGroupPublic,
    UserGroupUpdateRequest,
)

router = APIRouter()

# Membership changes write a mandatory audit entry in their transaction; it
# commits before the response, so the change and its entry go together.
_MembershipContainer = Annotated[
    Container, Depends(get_container(with_user=True, transaction_scope="function"))
]


@router.get(
    "/",
    response_model=PaginatedResponse[UserGroupPublic],
    description="List all user groups in the tenant.",
    responses=responses.get_responses([]),
)
async def get_user_groups(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.user_group_service()
    user_groups = await service.get_all_user_groups()

    return to_paginated_response(user_groups)


@router.get(
    "/{id}/",
    response_model=UserGroupPublic,
    description="Get a single user group by id.",
    responses=responses.get_responses([404]),
)
async def get_user_group_by_uuid(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.user_group_service()
    return await service.get_user_group_by_uuid(id)


@router.post(
    "/",
    response_model=UserGroupPublic,
    description="Create a new user group.",
    responses=responses.get_responses([400, 403]),
)
async def create_user_group(
    user_group: UserGroupCreateRequest,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.user_group_service()
    return await service.create_user_group(user_group)


@router.post(
    "/{id}/",
    response_model=UserGroupPublic,
    description=(
        "Update an existing user group by id. Every user added to or removed"
        " from the group is always recorded in the audit log."
    ),
    responses=responses.get_responses([400, 401, 403, 404]),
)
async def update_user_group(
    id: UUID,
    user_group: UserGroupUpdateRequest,
    container: _MembershipContainer,
):
    service = container.user_group_service()
    return await service.update_user_group(
        user_group_uuid=id, user_group_update=user_group
    )


@router.delete(
    "/{id}/",
    response_model=UserGroupPublic,
    description="Delete a user group by id.",
    responses=responses.get_responses([403, 404]),
)
async def delete_user_group_by_uuid(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.user_group_service()
    return await service.delete_user_group(id)


@router.post(
    "/{id}/users/{user_id}/",
    response_model=UserGroupPublic,
    description=(
        "Add a user to a user group. The user gets the group's role in every"
        " space the group belongs to. Always recorded in the audit log."
    ),
    responses=responses.get_responses([401, 403, 404]),
)
async def add_user_to_user_group(
    id: UUID,
    user_id: UUID,
    container: _MembershipContainer,
):
    service = container.user_group_service()
    return await service.add_user(user_group_uuid=id, user_id=user_id)


@router.delete(
    "/{id}/users/{user_id}/",
    response_model=UserGroupPublic,
    description=("Remove a user from a user group. Always recorded in the audit log."),
    responses=responses.get_responses([403, 404]),
)
async def delete_user_from_user_group(
    id: UUID,
    user_id: UUID,
    container: _MembershipContainer,
):
    service = container.user_group_service()
    return await service.remove_user(user_group_uuid=id, user_id=user_id)
