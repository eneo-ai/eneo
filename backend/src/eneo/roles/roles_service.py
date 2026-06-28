# MIT License

from uuid import UUID

from eneo.main.exceptions import BadRequestException, NotFoundException
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
from eneo.server.dependencies.predefined_roles import (
    load_predefined_roles_from_config,
)
from eneo.users.user import UserInDB
from eneo.users.user_repo import UsersRepository


class RolesService:
    def __init__(
        self,
        user: UserInDB,
        repo: RolesRepository,
        user_repo: UsersRepository | None = None,
    ) -> None:
        self.user = user
        self.repo = repo
        self.user_repo = user_repo

    def _validate(self, role: RoleInDB | None, role_id: UUID) -> RoleInDB:
        if role is None or self.user.tenant_id != role.tenant_id:
            raise NotFoundException(
                f"Role {role_id} not found for tenant({self.user.tenant_id})"
            )
        return role

    async def get_permissions(self) -> list[PermissionPublic]:
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
        return self._validate(role, role_id)

    async def _ensure_admin_survives(
        self, role: RoleInDB, removing_admin: bool, deleting: bool = False
    ):
        """Prevent changes that would leave the tenant with zero admin users."""
        if self.user_repo is None:
            return

        has_admin = Permission.ADMIN in (role.permissions or [])

        if deleting and has_admin:
            # Deleting a role with admin — check if other roles still cover admin users
            count = await self.user_repo.count_users_with_admin_permission(
                self.user.tenant_id, exclude_role_id=role.id
            )
            if count == 0:
                raise BadRequestException(
                    "Cannot delete this role — it is the only source of admin access. "
                    "At least one user must retain admin permissions."
                )

        if removing_admin and has_admin:
            # Removing admin permission from a role — same check
            count = await self.user_repo.count_users_with_admin_permission(
                self.user.tenant_id, exclude_role_id=role.id
            )
            if count == 0:
                raise BadRequestException(
                    "Cannot remove admin permission from this role — "
                    "it is the only source of admin access. "
                    "At least one user must retain admin permissions."
                )

    def _is_tenant_default_role(self, role_id: UUID) -> bool:
        """True if this role is the tenant's default — the role newly-
        provisioned users are assigned. Deletion is guarded so new users
        don't become role-less; edits are allowed so admins can manage
        permissions from one place (e.g. remove `shared_spaces` from the
        'User' role to restrict space creation).
        """
        return self.user.tenant.default_role_id == role_id

    @validate_permissions(Permission.ADMIN)
    async def update_role(self, role_update: RoleUpdateRequest, role_id: UUID):
        role = await self.get_role_by_uuid(role_id)

        # Check if admin permission is being removed
        removing_admin = (
            role_update.permissions is not None
            and Permission.ADMIN not in role_update.permissions
        )
        await self._ensure_admin_survives(role, removing_admin=removing_admin)

        role_update = RoleUpdate(
            **role_update.model_dump(exclude_unset=True), id=role.id
        )
        return await self.repo.update_role(role_update)

    @validate_permissions(Permission.ADMIN)
    async def delete_role(self, role_id: UUID):
        role = await self.get_role_by_uuid(role_id)

        await self._ensure_admin_survives(role, removing_admin=False, deleting=True)

        # Prevent deleting the tenant's default role
        if self._is_tenant_default_role(role_id):
            raise BadRequestException(
                "Cannot delete the tenant's default role. Change the default role first."
            )

        return await self.repo.delete_role_by_id(role_id)

    @validate_permissions(Permission.ADMIN)
    async def reset_role_to_default(self, role_id: UUID) -> RoleInDB:
        role = await self.get_role_by_uuid(role_id)

        if not role.predefined_source:
            raise BadRequestException(
                f"Role '{role.name}' is not a default role and cannot be reset."
            )

        templates = load_predefined_roles_from_config()
        template = next(
            (t for t in templates if t["name"] == role.predefined_source), None
        )
        if template is None:
            raise NotFoundException(
                f"Template for '{role.predefined_source}' not found in configuration."
            )

        # Check if reset would remove admin permission
        removing_admin = (
            Permission.ADMIN in (role.permissions or [])
            and "admin" not in template["permissions"]
        )
        await self._ensure_admin_survives(role, removing_admin=removing_admin)

        role_update = RoleUpdate(
            id=role.id,
            name=template["name"],
            permissions=template["permissions"],
        )
        updated = await self.repo.update_role(role_update)
        assert updated is not None
        return updated

    @validate_permissions(Permission.ADMIN)
    async def get_all_roles(self):
        return await self.repo.get_by_tenant(tenant_id=self.user.tenant_id)
