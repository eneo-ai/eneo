# MIT License

from intric.main.models import PaginatedResponse
from intric.predefined_roles.predefined_role import (
    PredefinedRoleInDB,
    PredefinedRolePublic,
)
from intric.roles.role import RoleInDB, RolePublic


def to_roles_paginated_response(
    roles: list[RoleInDB], predefined_roles: list[PredefinedRoleInDB]
):
    roles_response = PaginatedResponse(
        count=len(roles),  # type: ignore[call-arg]
        items=[RolePublic(**role.model_dump()) for role in roles],
    )
    predefined_roles_response = PaginatedResponse(
        count=len(predefined_roles),  # type: ignore[call-arg]
        items=[PredefinedRolePublic(**role.model_dump()) for role in predefined_roles],
    )
    return {"roles": roles_response, "predefined_roles": predefined_roles_response}
