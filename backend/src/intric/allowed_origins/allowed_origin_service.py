from intric.allowed_origins.allowed_origin_repo import AllowedOriginRepository
from intric.roles.permissions import Permission, validate_permissions
from intric.users.user import UserInDB


class AllowedOriginService:
    def __init__(self, user: UserInDB, repo: AllowedOriginRepository) -> None:
        super().__init__()
        self.user = user
        self.repo = repo

    @validate_permissions(Permission.ADMIN)
    async def get(self):
        return await self.repo.get_by_tenant(self.user.tenant_id)
