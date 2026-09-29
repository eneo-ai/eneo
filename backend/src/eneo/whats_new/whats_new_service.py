from fastapi import HTTPException, status

from eneo.main.config import get_settings
from eneo.users.user import UserInDB
from eneo.whats_new.whats_new_models import WhatsNewStatePublic
from eneo.whats_new.whats_new_repo import WhatsNewRepository


class WhatsNewService:
    def __init__(self, user: UserInDB, repo: WhatsNewRepository) -> None:
        super().__init__()
        self.user = user
        self.repo = repo

    async def get_state(self) -> WhatsNewStatePublic:
        return await self.repo.get_state(self.user.id)

    async def mark_seen(self, version: str) -> WhatsNewStatePublic:
        return await self.repo.mark_seen(self.user.id, version)

    async def mark_announced(self, version: str) -> WhatsNewStatePublic:
        return await self.repo.mark_announced(self.user.id, version)

    async def reset_state(self) -> WhatsNewStatePublic:
        """Developer convenience: forget both markers for the current user so
        the announcement and the dot come back. Only in development."""
        if not get_settings().is_development:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "developer_tools_disabled",
                    "message": "Developer tools are only available in development.",
                },
            )
        return await self.repo.reset(self.user.id)
