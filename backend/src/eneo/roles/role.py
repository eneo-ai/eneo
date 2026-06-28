# MIT License
from uuid import UUID

from pydantic import BaseModel

from eneo.main.models import InDB, PaginatedResponse
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
    predefined_source: str | None = None


class RoleUpdateRequest(RoleBase):
    name: str | None = None  # type: ignore[assignment]  # intentional widening to Optional for partial update
    permissions: list[Permission] | None = None  # type: ignore[assignment]  # intentional widening to Optional for partial update


class RoleUpdate(RoleUpdateRequest):
    id: UUID


class RoleInDB(RoleBase, InDB):
    tenant_id: UUID
    predefined_source: str | None = None


class RolePublic(RoleBase, InDB):
    predefined_source: str | None = None


class RolesPaginatedResponse(BaseModel):
    roles: PaginatedResponse[RolePublic]
    predefined_roles: PaginatedResponse[RolePublic]
