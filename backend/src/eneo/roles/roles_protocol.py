# MIT License

from eneo.main.models import PaginatedResponse
from eneo.roles.role import RoleInDB, RolePublic, RolesPaginatedResponse


def to_roles_paginated_response(roles: list[RoleInDB]) -> RolesPaginatedResponse:
    roles_response: PaginatedResponse[RolePublic] = PaginatedResponse[RolePublic](
        items=[RolePublic(**role.model_dump()) for role in roles],
    )
    # Empty predefined_roles for backward compatibility with the pre-unification API shape.
    predefined_roles_response: PaginatedResponse[RolePublic] = PaginatedResponse[
        RolePublic
    ](
        items=[],
    )
    return RolesPaginatedResponse(
        roles=roles_response, predefined_roles=predefined_roles_response
    )
