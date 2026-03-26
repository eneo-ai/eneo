# MIT License

from intric.main.models import PaginatedResponse
from intric.roles.role import RoleInDB, RolePublic


def to_roles_paginated_response(roles: list[RoleInDB]):
    roles_response = PaginatedResponse(
        count=len(roles), items=[RolePublic(**role.model_dump()) for role in roles]
    )
    # Empty predefined_roles for backward compatibility
    predefined_roles_response = PaginatedResponse(count=0, items=[])
    return {"roles": roles_response, "predefined_roles": predefined_roles_response}
