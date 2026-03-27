# MIT License
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from eneo.main.models import InDB, PaginatedResponse
from eneo.predefined_roles.predefined_role import PredefinedRolePublic
from eneo.roles.permissions import Permission


class PermissionPublic(BaseModel):
    name: Permission
    description: str


class RoleBase(BaseModel):
    name: str
    permissions: list[Permission]


class RoleCreateRequest(RoleBase):
    pass


class RoleCreate(RoleCreateRequest):
    tenant_id: UUID


class RoleUpdateRequest(RoleBase):
    name: Optional[str] = None
    permissions: Optional[list[Permission]] = None


class RoleUpdate(RoleUpdateRequest):
    id: UUID


class RoleInDB(RoleBase, InDB):
    tenant_id: UUID


class RolePublic(RoleBase, InDB):
    pass


class RolesPaginatedResponse(BaseModel):
    roles: PaginatedResponse[RolePublic]
    predefined_roles: PaginatedResponse[PredefinedRolePublic]
