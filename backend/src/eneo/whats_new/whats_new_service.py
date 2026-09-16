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
