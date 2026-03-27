# MIT License

from eneo.main.models import PaginatedResponse
from eneo.predefined_roles.predefined_role import (
    PredefinedRoleInDB,
    PredefinedRolePublic,
)
from eneo.roles.role import RoleInDB, RolePublic


def to_roles_paginated_response(
    roles: list[RoleInDB], predefined_roles: list[PredefinedRoleInDB]
):
    roles_response = PaginatedResponse(
        count=len(roles), items=[RolePublic(**role.model_dump()) for role in roles]
    )
    predefined_roles_response = PaginatedResponse(
        count=len(predefined_roles),
        items=[PredefinedRolePublic(**role.model_dump()) for role in predefined_roles],
    )
    return {"roles": roles_response, "predefined_roles": predefined_roles_response}
