# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""Routes for tenant-admin space oversight.

``read_router`` accepts tenant-admin API keys, like the admin widget
overview. ``manage_router`` is mounted session-only: an API key must never
make itself a content reader, and service keys have no users row to join
with.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eneo.main.container.container import Container
from eneo.roles.permissions import Permission, validate_permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.spaces.oversight.oversight_models import (
    AdminSpaceDetail,
    AdminSpaceGroupAdd,
    AdminSpaceJoin,
    AdminSpaceList,
    AdminSpaceMemberAdd,
    AdminSpaceMembers,
    AdminSpaceRoleUpdate,
)

read_router = APIRouter()
manage_router = APIRouter()


@read_router.get(
    "/",
    response_model=AdminSpaceList,
    description=(
        "Every shared space in the organisation with its administrators,"
        " member and resource counts, widget states, coarse last activity and"
        " your own membership, plus the pending widget activation requests."
        " Personal spaces and the organisation space are not listed. No"
        " content is returned. Tenant admins only."
    ),
    responses=responses.get_responses([403]),
)
async def list_admin_spaces(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    validate_permission(container.user(), Permission.ADMIN)
    return await container.space_oversight_service().list_spaces()


@read_router.get(
    "/{space_id}/",
    response_model=AdminSpaceDetail,
    description=(
        "Configuration, members and usage of one shared space: settings,"
        " assistants and apps with their instructions, knowledge sources with"
        " document counts, widgets and members. Documents, questions, answers,"
        " file names and conversations are never returned. Usage counts are"
        " withheld below five active users. Tenant admins only; personal"
        " spaces, the organisation space and other organisations' spaces are"
        " not found."
    ),
    responses=responses.get_responses([403, 404]),
)
async def get_admin_space(
    space_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    validate_permission(container.user(), Permission.ADMIN)
    return await container.space_oversight_service().get_space(space_id)


_MutationContainer = Annotated[
    Container, Depends(get_container(with_user=True, transaction_scope="function"))
]


@manage_router.post(
    "/{space_id}/members/",
    response_model=AdminSpaceMembers,
    status_code=201,
    description=(
        "Add a person to a shared space without being a member yourself."
        " Refused for yourself (join instead) and for an existing member."
        " Always recorded in the audit log."
    ),
    responses=responses.get_responses([400, 403, 404, 409]),
)
async def add_admin_space_member(
    space_id: UUID, body: AdminSpaceMemberAdd, container: _MutationContainer
):
    return await container.space_oversight_service().add_member(
        space_id, body.user_id, body.role
    )


@manage_router.patch(
    "/{space_id}/members/{user_id}/",
    response_model=AdminSpaceMembers,
    description=(
        "Change a member's role. Refused for yourself and when it would leave"
        " the space without an administrator who can manage it. Always"
        " recorded in the audit log."
    ),
    responses=responses.get_responses([400, 403, 404, 409]),
)
async def change_admin_space_member_role(
    space_id: UUID,
    user_id: UUID,
    body: AdminSpaceRoleUpdate,
    container: _MutationContainer,
):
    return await container.space_oversight_service().change_member_role(
        space_id, user_id, body.role
    )


@manage_router.delete(
    "/{space_id}/members/{user_id}/",
    response_model=AdminSpaceMembers,
    description=(
        "Remove a member and revoke the API keys they own for the space."
        " Refused for yourself (leave instead) and when it would leave the"
        " space without an administrator. Always recorded in the audit log."
    ),
    responses=responses.get_responses([400, 403, 404, 409]),
)
async def remove_admin_space_member(
    space_id: UUID, user_id: UUID, container: _MutationContainer
):
    return await container.space_oversight_service().remove_member(space_id, user_id)


@manage_router.post(
    "/{space_id}/group-members/",
    response_model=AdminSpaceMembers,
    status_code=201,
    description=(
        "Add a user group to a shared space. Refused when the group is"
        " already a member, and when it contains you and would raise your"
        " own role (join instead). Always recorded in the audit log."
    ),
    responses=responses.get_responses([400, 403, 404, 409]),
)
async def add_admin_space_group(
    space_id: UUID, body: AdminSpaceGroupAdd, container: _MutationContainer
):
    return await container.space_oversight_service().add_group(
        space_id, body.group_id, body.role
    )


@manage_router.patch(
    "/{space_id}/group-members/{group_id}/",
    response_model=AdminSpaceMembers,
    description=(
        "Change a group's role. Refused when the group contains you and the"
        " change raises your own role, and when it would leave the space"
        " without an administrator. Always recorded in the audit log."
    ),
    responses=responses.get_responses([400, 403, 404, 409]),
)
async def change_admin_space_group_role(
    space_id: UUID,
    group_id: UUID,
    body: AdminSpaceRoleUpdate,
    container: _MutationContainer,
):
    return await container.space_oversight_service().change_group_role(
        space_id, group_id, body.role
    )


@manage_router.delete(
    "/{space_id}/group-members/{group_id}/",
    response_model=AdminSpaceMembers,
    description=(
        "Remove a group from a shared space. Refused when it would leave the"
        " space without an administrator. Always recorded in the audit log."
    ),
    responses=responses.get_responses([403, 404, 409]),
)
async def remove_admin_space_group(
    space_id: UUID, group_id: UUID, container: _MutationContainer
):
    return await container.space_oversight_service().remove_group(space_id, group_id)


@manage_router.post(
    "/{space_id}/join/",
    response_model=AdminSpaceMembers,
    description=(
        "Join a shared space to reach its content, with a role and a written"
        " reason. With a group membership only roles above the group role are"
        " allowed. The space's members see that you joined, its"
        " administrators also see the reason, and the audit log always"
        " records it."
    ),
    responses=responses.get_responses([400, 403, 404, 409]),
)
async def join_admin_space(
    space_id: UUID, body: AdminSpaceJoin, container: _MutationContainer
):
    return await container.space_oversight_service().join(
        space_id, body.role, body.reason
    )


@manage_router.post(
    "/{space_id}/leave/",
    response_model=AdminSpaceMembers,
    description=(
        "Leave a shared space you are a direct member of and revoke the API"
        " keys you own for it. A role held through a group remains. Refused"
        " when you are its last administrator. Always recorded in the audit"
        " log."
    ),
    responses=responses.get_responses([400, 403, 404, 409]),
)
async def leave_admin_space(space_id: UUID, container: _MutationContainer):
    return await container.space_oversight_service().leave(space_id)
