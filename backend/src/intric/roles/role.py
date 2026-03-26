# MIT License
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from intric.main.models import InDB, PaginatedResponse
from intric.roles.permissions import Permission


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
    predefined_source: Optional[str] = None


class RoleUpdateRequest(RoleBase):
    name: Optional[str] = None
    permissions: Optional[list[Permission]] = None


class RoleUpdate(RoleUpdateRequest):
    id: UUID


class RoleInDB(RoleBase, InDB):
    tenant_id: UUID
    predefined_source: Optional[str] = None


class RolePublic(RoleBase, InDB):
    predefined_source: Optional[str] = None


class RolesPaginatedResponse(BaseModel):
    roles: PaginatedResponse[RolePublic]
    predefined_roles: PaginatedResponse[RolePublic]
