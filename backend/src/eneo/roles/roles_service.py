# MIT License

from uuid import UUID

from eneo.main.exceptions import NotFoundException
from eneo.roles.permissions import Permission, validate_permissions
from eneo.roles.permissions_mapper import PERMISSIONS_WITH_DESCRIPTION
from eneo.roles.role import (
    PermissionPublic,
    RoleCreate,
    RoleCreateRequest,
    RoleInDB,
    RoleUpdate,
    RoleUpdateRequest,
)
from eneo.roles.roles_repo import RolesRepository
from eneo.users.user import UserInDB


class RolesService:
    def __init__(
        self,
        user: UserInDB,
        repo: RolesRepository,
    ):
        self.user = user
        self.repo = repo

    def _validate(self, role: RoleInDB, role_id: UUID):
        if role is None or self.user.tenant_id != role.tenant_id:
            raise NotFoundException(
                f"Role {role_id} not found for tenant({self.user.tenant_id})"
            )

    async def get_permissions(self) -> dict:
        return [
            PermissionPublic(name=key, description=value)
            for key, value in PERMISSIONS_WITH_DESCRIPTION.items()
        ]

    @validate_permissions(Permission.ADMIN)
    async def create_role(self, role: RoleCreateRequest) -> RoleInDB:
        role = RoleCreate(
            name=role.name, permissions=role.permissions, tenant_id=self.user.tenant_id
        )
        return await self.repo.create_role(role)

    @validate_permissions(Permission.ADMIN)
    async def get_role_by_uuid(self, role_id: UUID) -> RoleInDB:
        role = await self.repo.get_role(role_id)
        self._validate(role, role_id)

        return role

    @validate_permissions(Permission.ADMIN)
    async def update_role(self, role_update: RoleUpdateRequest, role_id: UUID):
        role = await self.get_role_by_uuid(role_id)
        self._validate(role, role_id)

        role_update = RoleUpdate(
            **role_update.model_dump(exclude_unset=True), id=role.id
        )
        return await self.repo.update_role(role_update)

    @validate_permissions(Permission.ADMIN)
    async def delete_role(self, role_id: UUID):
        role = await self.get_role_by_uuid(role_id)
        self._validate(role, role_id)

        return await self.repo.delete_role_by_id(role_id)

    @validate_permissions(Permission.ADMIN)
    async def get_all_roles(self):
        return await self.repo.get_by_tenant(tenant_id=self.user.tenant_id)
