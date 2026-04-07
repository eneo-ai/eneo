# MIT License

from uuid import UUID

from intric.main.exceptions import NotFoundException
from intric.predefined_roles.predefined_role import PredefinedRoleInDB
from intric.predefined_roles.predefined_roles_repo import PredefinedRolesRepository


class PredefinedRolesService:
    def __init__(self, repo: PredefinedRolesRepository):
        super().__init__()
        self.repo = repo

    def _validate(self, role: PredefinedRoleInDB | None, role_id: UUID) -> None:
        if role is None:
            raise NotFoundException(f"PredefinedRole {role_id} not found")

    async def get_predefined_role(self, role_id: UUID) -> PredefinedRoleInDB:
        role = await self.repo.get_predefined_role_by_uuid(role_id)
        self._validate(role, role_id)
        assert role is not None

        return role

    async def get_predefined_roles(self) -> list[PredefinedRoleInDB]:
        return await self.repo.get_predefined_roles()
