# MIT License

from intric.main.models import PaginatedResponse
from intric.predefined_roles.predefined_role import (
    PredefinedRoleInDB,
    PredefinedRolePublic,
)
from intric.roles.role import RoleInDB, RolePublic, RolesPaginatedResponse


def to_roles_paginated_response(
    roles: list[RoleInDB], predefined_roles: list[PredefinedRoleInDB]
) -> RolesPaginatedResponse:
    roles_response: PaginatedResponse[RolePublic] = PaginatedResponse[RolePublic](
        items=[RolePublic(**role.model_dump()) for role in roles],
    )
    predefined_roles_response: PaginatedResponse[PredefinedRolePublic] = (
        PaginatedResponse[PredefinedRolePublic](
            items=[
                PredefinedRolePublic(**role.model_dump()) for role in predefined_roles
            ],
        )
    )
    return RolesPaginatedResponse(
        roles=roles_response, predefined_roles=predefined_roles_response
    )
